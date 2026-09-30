"""
FastAPI backend (plan_v2.md Section 15, Phase 2 - Production/Scale).

Wraps the existing app/ pipeline, validation_views, and business_metrics
modules -- no business logic is duplicated here. This is a thin HTTP layer
consumed by the Next.js frontend (frontend/).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.business_metrics import METRIC_REGISTRY
from app.config import (
    DATASETS,
    MAPPING_DIR,
    RUN_LOG_DIR,
    load_data_source_registry,
    set_dataset_source_type,
)
from app.export import export_all, export_optilogic_ready
from app.extraction import (
    get_uploaded_file_path,
    list_available_odbc_drivers,
    load_extraction_config,
    save_extraction_config,
    save_uploaded_file,
    sql_extraction_is_configured,
    test_sql_connection,
)
from app.pipeline import bronze_to_gold, extract_to_bronze, load_gold, run_full_pipeline
from app.flow_maps import build_inbound_od_map, build_outbound_od_map
from app.validation_views import (
    get_ai_fill_review,
    get_cross_reference_exceptions,
    get_dataset_quality_summary,
    get_issue_flagged,
    get_raw_vs_validated,
    load_run_summary,
)

app = FastAPI(title="Network Design Data Prep API", version="1.0.0")

# Ensure OpenAPI schema always reflects all routes.
# (In some environments, FastAPI's schema caching can miss late-bound routes
# when the module import order differs between runtime and tests.)
from fastapi.openapi.utils import get_openapi


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df_to_records(df) -> List[dict]:
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _list_run_ids(project_id: str) -> List[str]:
    run_log_dir = RUN_LOG_DIR / project_id
    if not run_log_dir.exists():
        return []
    summaries = sorted(run_log_dir.glob("*_summary.json"))
    run_ids = [p.name.replace("_summary.json", "") for p in summaries]
    return sorted(run_ids, reverse=True)


class RunPipelineRequest(BaseModel):
    project_id: str
    use_sample_data: Optional[bool] = None  # None = auto-detect (sql if configured, else sample)


class ReviewDecisionRequest(BaseModel):
    decision: str  # "approve" | "reject" | "replace" | "unresolved"
    corrected_value: Optional[str] = None
    reviewer: Optional[str] = None
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Health / config
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config/sql-status")
def sql_status():
    return {"sql_configured": sql_extraction_is_configured()}


class SqlConnectionConfig(BaseModel):
    server: str
    database: str
    driver: str = "ODBC Driver 17 for SQL Server"
    queries: dict  # dataset -> {load_mode, watermark_column, query}


class TestConnectionRequest(BaseModel):
    server: str
    database: str
    driver: str = "ODBC Driver 17 for SQL Server"


@app.get("/config/sql-connection")
def get_sql_connection():
    try:
        cfg = load_extraction_config()
    except FileNotFoundError:
        cfg = {"connection": {"server": "", "database": "", "driver": "ODBC Driver 17 for SQL Server"}, "datasets": {}}
    return cfg


@app.get("/config/odbc-drivers")
def get_odbc_drivers():
    return {"drivers": list_available_odbc_drivers()}


@app.post("/config/sql-connection/test")
def test_sql_connection_endpoint(req: TestConnectionRequest):
    result = test_sql_connection(req.server, req.database, req.driver)
    return result


@app.post("/config/sql-connection")
def save_sql_connection(cfg: SqlConnectionConfig):
    new_cfg = {
        "connection": {
            "server": cfg.server,
            "database": cfg.database,
            "driver": cfg.driver,
        },
        "datasets": cfg.queries,
    }
    save_extraction_config(new_cfg)
    return {"status": "saved", "sql_configured": sql_extraction_is_configured()}


# ---------------------------------------------------------------------------
# Data Sources (per-dataset: SQL / File Upload / None) -- makes every
# dataset optional; the pipeline runs successfully with whatever is available.
# ---------------------------------------------------------------------------

class SetSourceTypeRequest(BaseModel):
    source_type: str  # "sql" | "file" | "none"


@app.get("/data-sources/{project_id}")
def get_data_sources(project_id: str):
    registry = load_data_source_registry(project_id)
    for dataset in DATASETS:
        entry = registry.get(dataset, {"source_type": "none", "upload_filename": None})
        uploaded_path = get_uploaded_file_path(project_id, dataset)
        entry["uploaded_filename"] = uploaded_path.name if uploaded_path else None
        registry[dataset] = entry
    return {"project_id": project_id, "datasets": registry}


@app.post("/data-sources/{project_id}/{dataset}/source-type")
def set_data_source_type(project_id: str, dataset: str, req: SetSourceTypeRequest):
    if req.source_type not in ("sql", "file", "none"):
        raise HTTPException(status_code=400, detail="source_type must be 'sql', 'file', or 'none'")
    if dataset not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Unknown dataset '{dataset}'")
    set_dataset_source_type(project_id, dataset, req.source_type)
    return {"status": "updated", "dataset": dataset, "source_type": req.source_type}


@app.post("/data-sources/{project_id}/{dataset}/upload")
async def upload_dataset_file(project_id: str, dataset: str, file: UploadFile = File(...)):
    if dataset not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Unknown dataset '{dataset}'")
    content = await file.read()
    try:
        path = save_uploaded_file(project_id, dataset, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    set_dataset_source_type(project_id, dataset, "file")

    # Auto-refresh the column mapping so it reflects the new file's actual columns.
    import pandas as pd
    from app.column_mapping import run_mapping_suggestion_for_dataset

    try:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            raw_df = pd.read_csv(path)
        else:
            raw_df = pd.read_excel(path)
        mapping_entries = run_mapping_suggestion_for_dataset(project_id, dataset, raw_df, overwrite=True)
        approved_count = sum(1 for e in mapping_entries if e.get("approved"))
        total_count = len(mapping_entries)
    except Exception:  # noqa: BLE001
        approved_count = 0
        total_count = 0

    return {
        "status": "uploaded",
        "dataset": dataset,
        "filename": path.name,
        "path": str(path),
        "mapping_refreshed": True,
        "approved_mappings": approved_count,
        "total_columns": total_count,
    }


@app.post("/mappings/{project_id}/{dataset}/refresh")
def refresh_mapping(project_id: str, dataset: str):
    """Re-run mapping suggestion for a dataset based on its currently uploaded file."""
    import pandas as pd
    from app.column_mapping import run_mapping_suggestion_for_dataset
    from app.extraction import get_uploaded_file_path

    path = get_uploaded_file_path(project_id, dataset)
    if path is None:
        raise HTTPException(status_code=404, detail=f"[{dataset}] No uploaded file found for this dataset.")
    try:
        suffix = path.suffix.lower()
        raw_df = pd.read_csv(path) if suffix == ".csv" else pd.read_excel(path)
        entries = run_mapping_suggestion_for_dataset(project_id, dataset, raw_df, overwrite=True)
        return {"status": "refreshed", "dataset": dataset, "entries": entries}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"[{dataset}] {exc}")


# ---------------------------------------------------------------------------
# Extraction / Pipeline (Section 15: POST /extract, POST /etl/run)
# ---------------------------------------------------------------------------

@app.post("/pipeline/run")
def run_pipeline(req: RunPipelineRequest):
    try:
        summary = run_full_pipeline(req.project_id, use_sample_data=req.use_sample_data)
        return summary
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/pipeline/extract-only")
def extract_only(req: RunPipelineRequest):
    """Phase 1: Extract raw data to Bronze + auto-run mapping suggestions.
    Returns run_id + raw column preview per dataset for mapping review (Phase 2)."""
    try:
        summary = extract_to_bronze(req.project_id, use_sample_data=req.use_sample_data)
        return summary
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


class BronzeToGoldRequest(BaseModel):
    project_id: str
    run_id: str


class RefreshAllMappingsRequest(BaseModel):
    project_id: str
    run_id: str


@app.post("/pipeline/refresh-all-mappings")
def refresh_all_mappings(req: RefreshAllMappingsRequest):
    """Re-run mapping suggestion for all datasets in an existing Bronze run.
    Use this to fix stale mapping configs when the extraction has already been done."""
    import pandas as pd
    from app.column_mapping import run_mapping_suggestion_for_dataset
    from app.config import BRONZE_DIR

    refreshed = []
    errors = {}
    bronze_project = BRONZE_DIR / req.project_id
    for ds in DATASETS:
        ds_path = bronze_project / ds / req.run_id / "data.parquet"
        if not ds_path.exists():
            continue
        try:
            raw_df = pd.read_parquet(ds_path)
            entries = run_mapping_suggestion_for_dataset(req.project_id, ds, raw_df, overwrite=True)
            refreshed.append({"dataset": ds, "column_count": len(raw_df.columns), "entry_count": len(entries)})
        except Exception as exc:  # noqa: BLE001
            errors[ds] = str(exc)
    return {"status": "refreshed", "run_id": req.run_id, "datasets": refreshed, "errors": errors}


@app.post("/pipeline/run-from-bronze")
def run_from_bronze(req: BronzeToGoldRequest):
    """Phase 3: Silver → Profile → Validate → Enrich → Gold using existing Bronze data.
    Call this after user has reviewed/confirmed column mappings in Phase 2."""
    try:
        summary = bronze_to_gold(req.project_id, req.run_id)
        return summary
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/runs/{project_id}")
def list_runs(project_id: str):
    return {"project_id": project_id, "runs": _list_run_ids(project_id)}


@app.get("/runs/{project_id}/{run_id}/summary")
def run_summary(project_id: str, run_id: str):
    summary = load_run_summary(project_id, run_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Run summary not found")
    return summary


# ---------------------------------------------------------------------------
# Profiling (Section 15: GET /runs/{id}/profile)
# ---------------------------------------------------------------------------

@app.get("/runs/{project_id}/{run_id}/profile/{dataset}")
def get_profile(project_id: str, run_id: str, dataset: str):
    profile_path = RUN_LOG_DIR / project_id / "profiles" / dataset / f"{run_id}.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")
    with open(profile_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Dataset quality (Section 15: GET /runs/{id}/summary at dataset level)
# ---------------------------------------------------------------------------

@app.get("/runs/{project_id}/{run_id}/quality")
def dataset_quality(project_id: str, run_id: str):
    return {ds: get_dataset_quality_summary(project_id, ds, run_id) for ds in DATASETS}


# ---------------------------------------------------------------------------
# Issue log / cross-reference exceptions / review queue (Section 15)
# ---------------------------------------------------------------------------

@app.get("/runs/{project_id}/{run_id}/issues/{dataset}")
def issues(project_id: str, run_id: str, dataset: str,
           issue_type: Optional[str] = None, severity: Optional[str] = None):
    df = get_issue_flagged(project_id, dataset, run_id, issue_type=issue_type, severity=severity)
    return {"dataset": dataset, "count": len(df), "records": _df_to_records(df)}


@app.get("/runs/{project_id}/{run_id}/cross-reference-exceptions/{dataset}")
def cross_reference_exceptions(project_id: str, run_id: str, dataset: str):
    df = get_cross_reference_exceptions(project_id, dataset, run_id)
    if df.empty:
        return {"dataset": dataset, "count": 0, "records": []}

    # Aggregate by (field, invalid_value, expected_master, match_type) with count
    group_cols = [c for c in ["field", "invalid_value", "expected_master", "match_type"] if c in df.columns]
    if group_cols:
        agg = (
            df.groupby(group_cols, dropna=False)
            .agg(
                count=("record_id", "count"),
                first_record_id=("record_id", "first"),
                detected_at=("created_at", "first"),
            )
            .reset_index()
        )
        # Rename for clarity
        agg = agg.rename(columns={"first_record_id": "record_id"})
        records = json.loads(agg.to_json(orient="records", date_format="iso"))
    else:
        records = _df_to_records(df)

    return {"dataset": dataset, "count": len(df), "unique_exception_count": len(records), "records": records}


@app.get("/runs/{project_id}/{run_id}/review-queue/{dataset}")
def review_queue(project_id: str, run_id: str, dataset: str):
    df = get_ai_fill_review(project_id, dataset, run_id)
    return {"dataset": dataset, "count": len(df), "records": _df_to_records(df)}


@app.post("/review/{project_id}/{run_id}/{dataset}/{record_index}/decision")
def submit_review_decision(
    project_id: str, run_id: str, dataset: str, record_index: int, req: ReviewDecisionRequest
):
    """
    Record a manual review decision (approve/reject/replace/unresolved).
    Persisted as an append-only decision log per run (plan_v2.md Section 11).
    """
    decisions_path = RUN_LOG_DIR / project_id / f"{run_id}_review_decisions.jsonl"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset": dataset,
        "record_index": record_index,
        "decision": req.decision,
        "corrected_value": req.corrected_value,
        "reviewer": req.reviewer,
        "comment": req.comment,
    }
    with open(decisions_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return {"status": "recorded", "entry": entry}


# ---------------------------------------------------------------------------
# Validation views (Section 15: GET /views/{dataset})
# ---------------------------------------------------------------------------

@app.get("/views/{project_id}/{run_id}/{dataset}")
def raw_vs_validated(
    project_id: str, run_id: str, dataset: str,
    status_filter: str = Query("all", pattern="^(all|validated|flagged|unresolved)$"),
    limit: int = 500,
):
    df = get_raw_vs_validated(project_id, dataset, run_id, status_filter=status_filter)
    return {"dataset": dataset, "count": len(df), "records": _df_to_records(df.head(limit))}


# ---------------------------------------------------------------------------
# Business metrics (Section 15: GET /metrics/{dataset}/{metric_name})
# ---------------------------------------------------------------------------

@app.get("/metrics/{project_id}/{run_id}/{metric_name}")
def business_metric(
    project_id: str, run_id: str, metric_name: str,
    status_filter: str = Query("all", pattern="^(all|validated|flagged|unresolved)$"),
):
    fn = METRIC_REGISTRY.get(metric_name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown metric '{metric_name}'")
    fig = fn(project_id, run_id, status_filter=status_filter)
    return json.loads(fig.to_json())


@app.get("/metrics")
def list_metrics():
    return {"metrics": list(METRIC_REGISTRY.keys())}


# ---------------------------------------------------------------------------
# Geographic OD Flow Maps (Inbound / Outbound)
# ---------------------------------------------------------------------------

@app.get("/flow-maps/{project_id}/{run_id}/inbound")
def inbound_flow_map(
    project_id: str,
    run_id: str,
    status_filter: str = Query("all", pattern="^(all|validated|flagged|unresolved)$"),
    top_n: int = 150,
    metric: str = Query("volume", pattern="^(volume|count)$"),
):
    return build_inbound_od_map(project_id, run_id, status_filter=status_filter, top_n=top_n, metric=metric)  # type: ignore[arg-type]


@app.get("/flow-maps/{project_id}/{run_id}/outbound")
def outbound_flow_map(
    project_id: str,
    run_id: str,
    status_filter: str = Query("all", pattern="^(all|validated|flagged|unresolved)$"),
    top_n: int = 150,
    metric: str = Query("volume", pattern="^(volume|count)$"),
):
    return build_outbound_od_map(project_id, run_id, status_filter=status_filter, top_n=top_n, metric=metric)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Column mapping review (Section 15/16)
# ---------------------------------------------------------------------------

@app.get("/mappings/{project_id}/{dataset}")
def get_mapping(project_id: str, dataset: str):
    path = MAPPING_DIR / project_id / f"{dataset}.json"
    if not path.exists():
        return {"dataset": dataset, "entries": []}
    with open(path, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    return {"dataset": dataset, "entries": entries}


class MappingPatchRequest(BaseModel):
    entries: list


@app.post("/mappings/{project_id}/{dataset}/patch")
def patch_mapping(project_id: str, dataset: str, req: MappingPatchRequest):
    """Replace the entire mapping entries list (used for manual overrides)."""
    from app.config import save_mapping_config
    try:
        save_mapping_config(project_id, dataset, req.entries)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"[{dataset}] Failed to save mapping: {exc}")
    return {"status": "patched", "dataset": dataset, "count": len(req.entries)}


@app.post("/mappings/{project_id}/{dataset}/{raw_column}/approve")
def approve_mapping(project_id: str, dataset: str, raw_column: str):
    path = MAPPING_DIR / project_id / f"{dataset}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"[{dataset}] Mapping config not found — run the pipeline first to generate mappings.")
    with open(path, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    found = False
    for e in entries:
        if e["raw_column"] == raw_column:
            e["approved"] = True
            e["approver"] = "manual_review"
            found = True
    if not found:
        raise HTTPException(status_code=404, detail=f"[{dataset}] No mapping entry found for raw column '{raw_column}'")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, default=str)
    return {"status": "approved", "raw_column": raw_column}


# ---------------------------------------------------------------------------
# Export (Section 15: GET /runs/{id}/export)
# ---------------------------------------------------------------------------

@app.post("/export/{project_id}/{run_id}")
def export_run(project_id: str, run_id: str):
    outputs = export_all(project_id, run_id, DATASETS)
    return outputs


@app.get("/export/{project_id}/{run_id}/{dataset}/optilogic")
def export_optilogic(project_id: str, run_id: str, dataset: str):
    path = export_optilogic_ready(project_id, dataset, run_id)
    return FileResponse(path, filename=Path(path).name, media_type="text/csv")


@app.get("/datasets")
def list_datasets():
    return {"datasets": DATASETS}


# ---------------------------------------------------------------------------
# AI Executive Insights (NTT AI Gateway / GPT-4o)
# ---------------------------------------------------------------------------

class AIDashboardRequest(BaseModel):
    project_id: str
    run_id: str
    scenario_a: Optional[str] = None  # run_id of run A (defaults to run_id)
    scenario_b: Optional[str] = None  # run_id of another run for comparison


class AIChatRequest(BaseModel):
    project_id: str
    run_id: str
    scenario_a: Optional[str] = None
    scenario_b: Optional[str] = None
    messages: list  # [{"role": "user"|"assistant", "content": "..."}]


def _build_reporting_df(project_id: str, run_id: str) -> "pd.DataFrame":
    """
    Build a flat reporting DataFrame from Gold data for use with AI insights.
    Adapts Gold parquet files into the ScenarioLens reporting format.
    """
    import pandas as pd
    from app.pipeline import load_gold
    from app.config import DATASETS, TRANSACTIONAL_DATASETS

    rows = []
    for dataset in DATASETS:
        try:
            df = load_gold(project_id, dataset, run_id)
        except FileNotFoundError:
            continue
        if df.empty:
            continue

        # Map canonical columns to reporting format
        is_shipment = "shipment" in dataset
        is_cost = dataset == "shipment_cost"

        for _, row in df.iterrows():
            base = {
                "ScenarioName": run_id,
                "Category": "Transactional" if dataset in TRANSACTIONAL_DATASETS else "Master",
                "SubCategory": dataset,
            }

            # Volume / cost mapping
            vol = 0.0
            cost = 0.0
            if "volume" in df.columns:
                try: vol = float(row.get("volume", 0) or 0)
                except: pass
            elif "raw__Quantity" in df.columns:
                try: vol = float(row.get("raw__Quantity", 0) or 0)
                except: pass
            if "quantity_on_hand" in df.columns:
                try: vol = float(row.get("quantity_on_hand", 0) or 0)
                except: pass
            if "cost_amount" in df.columns:
                try: cost = float(row.get("cost_amount", 0) or 0)
                except: pass

            # Flow direction
            direction = str(row.get("direction", "")).strip()
            if "inbound" in direction.lower():
                base["SubCategory"] = "InboundFlow"
            elif "outbound" in direction.lower():
                base["SubCategory"] = "OutboundFlow"
            elif is_cost:
                base["SubCategory"] = "ShipmentCost"
                base["CostSubCategory"] = "OutboundFreightCost"

            base["FlowVolume"] = vol
            base["Cost($)"] = cost
            base["OriginName"] = str(row.get("origin_location_id", row.get("location_id", "-")) or "-")
            base["DestinationName"] = str(row.get("destination_location_id", row.get("customer_id", "-")) or "-")
            base["Resource"] = str(row.get("product_id", "-") or "-")
            base["Mode"] = str(row.get("shipment_mode", "-") or "-")
            rows.append(base)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


@app.post("/ai-insights/dashboard")
def ai_dashboard(req: AIDashboardRequest):
    """Generate AI executive dashboard comparing two pipeline runs (or using current run)."""
    from app.ai_insights import generate_ai_dashboard
    import pandas as pd

    scenario_a = req.scenario_a or req.run_id
    scenario_b = req.scenario_b or req.run_id

    df = _build_reporting_df(req.project_id, req.run_id)
    if df.empty:
        raise HTTPException(status_code=404, detail="No Gold data found for this run. Run Phase 3 first.")

    # If comparing two runs, load both
    if scenario_b != scenario_a:
        df_b = _build_reporting_df(req.project_id, scenario_b)
        if not df_b.empty:
            df_b["ScenarioName"] = scenario_b
            df["ScenarioName"] = scenario_a
            df = pd.concat([df, df_b], ignore_index=True)
    else:
        df["ScenarioName"] = scenario_a

    try:
        result = generate_ai_dashboard(df, scenario_a, scenario_b)
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ai-insights/chat")
def ai_chat(req: AIChatRequest):
    """Answer a supply chain analysis question using AI with root-cause data."""
    from app.ai_insights import answer_chat_question
    import pandas as pd

    scenario_a = req.scenario_a or req.run_id
    scenario_b = req.scenario_b or req.run_id

    df = _build_reporting_df(req.project_id, req.run_id)
    if df.empty:
        raise HTTPException(status_code=404, detail="No Gold data found for this run.")

    if scenario_b != scenario_a:
        df_b = _build_reporting_df(req.project_id, scenario_b)
        if not df_b.empty:
            df_b["ScenarioName"] = scenario_b
            df["ScenarioName"] = scenario_a
            df = pd.concat([df, df_b], ignore_index=True)
    else:
        df["ScenarioName"] = scenario_a

    try:
        answer = answer_chat_question(df, scenario_a, scenario_b, req.messages)
        return {"answer": answer}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Silver Cleanup — LLM-assisted manual cleanup on Silver layer
# ---------------------------------------------------------------------------

class CleanupRequest(BaseModel):
    project_id: str
    run_id: str
    instructions: list  # list of cleanup instruction dicts
    approved_by: Optional[str] = "user"


@app.post("/silver-cleanup/{project_id}/{dataset}/{run_id}")
def apply_silver_cleanup(project_id: str, dataset: str, run_id: str, req: CleanupRequest):
    """
    Apply approved cleanup instructions to the Silver layer for a dataset.
    Never touches Bronze. Logs all decisions.
    """
    from app.silver_cleanup import apply_cleanup_instructions
    from app.silver_etl import load_silver

    try:
        silver_df = load_silver(project_id, dataset, run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"[{dataset}] No Silver data found for run {run_id}. Run Phase 3 first.")

    try:
        _, decision_log = apply_cleanup_instructions(
            silver_df, req.instructions, project_id, dataset, run_id,
            approved_by=req.approved_by or "user"
        )
        return {
            "status": "applied",
            "dataset": dataset,
            "run_id": run_id,
            "instructions_processed": len(req.instructions),
            "decisions": decision_log,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"[{dataset}] Cleanup failed: {exc}")


@app.post("/silver-cleanup/parse-nl")
def parse_natural_language_cleanup(req: dict):
    """
    Parse a natural language cleanup instruction into structured JSON using the AI Gateway.
    Accepts: {"text": "rename ShipDate to shipment_date, treat N/A as null in city"}
    Returns: {"instructions": [...], "raw_text": "..."}
    """
    from app.silver_cleanup import parse_natural_language_instructions
    nl_text = req.get("text", "").strip()
    if not nl_text:
        raise HTTPException(status_code=400, detail="text field is required")
    try:
        instructions = parse_natural_language_instructions(nl_text)
        return {"instructions": instructions, "parsed_from": nl_text}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/silver-cleanup/{project_id}/{dataset}/{run_id}/log")
def get_cleanup_log(project_id: str, dataset: str, run_id: str):
    """Get the cleanup decision log for a Silver run."""
    from app.silver_cleanup import load_cleanup_log
    return load_cleanup_log(project_id, dataset, run_id)


@app.get("/transform-log/{project_id}/{dataset}/{run_id}")
def get_transform_log(project_id: str, dataset: str, run_id: str):
    """Get the Silver transformation log (cleaning steps, outliers, grain) for a run."""
    from app.silver_etl import load_transform_log
    log = load_transform_log(project_id, dataset, run_id)
    if not log:
        raise HTTPException(status_code=404, detail=f"No transform log found for {dataset}/{run_id}")
    return log


# ---------------------------------------------------------------------------
# Data Stage Viewer — Bronze / Silver / Gold for a dataset
# ---------------------------------------------------------------------------

@app.get("/data-stages/{project_id}/{dataset}/{run_id}")
def data_stages(project_id: str, dataset: str, run_id: str, limit: int = 100):
    """
    Return a summary of Bronze, Silver, and Gold data for a specific dataset/run.
    Shows row counts, column counts, and sample records for each layer.
    """
    import pandas as pd
    from app.config import BRONZE_DIR, SILVER_DIR, GOLD_DIR

    result = {"project_id": project_id, "dataset": dataset, "run_id": run_id, "layers": {}}

    # Bronze
    bronze_path = BRONZE_DIR / project_id / dataset / run_id / "data.parquet"
    if bronze_path.exists():
        try:
            bdf = pd.read_parquet(bronze_path)
            result["layers"]["bronze"] = {
                "row_count": len(bdf),
                "column_count": len(bdf.columns),
                "columns": list(bdf.columns),
                "sample": json.loads(bdf.head(min(5, limit)).to_json(orient="records", date_format="iso")),
                "available": True,
            }
        except Exception as e:
            result["layers"]["bronze"] = {"available": False, "error": str(e)}
    else:
        result["layers"]["bronze"] = {"available": False, "note": "Not yet extracted"}

    # Silver
    from app.config import SILVER_DIR as _SILVER_DIR
    silver_path = _SILVER_DIR / project_id / dataset / run_id / "data.parquet"
    if silver_path.exists():
        try:
            sdf = pd.read_parquet(silver_path)
            # Load transform log summary
            from app.silver_etl import load_transform_log
            tlog = load_transform_log(project_id, dataset, run_id)

            # Scope filter is applied immediately after Silver — surface scope_included/
            # scope_excluded counts here so the UI reflects: Silver -> Scope Filter (this stage) -> ...
            scope_included_count = None
            scope_excluded_count = None
            if "scope_included" in sdf.columns:
                scope_included_count = int(sdf["scope_included"].sum())
                scope_excluded_count = int((~sdf["scope_included"]).sum())

            result["layers"]["silver"] = {
                "row_count": len(sdf),
                "column_count": len(sdf.columns),
                "columns": list(sdf.columns),
                "sample": json.loads(sdf.head(min(5, limit)).to_json(orient="records", date_format="iso")),
                "available": True,
                "grain_report": tlog.get("grain_report", {}),
                "transformations_count": len(tlog.get("transformations", [])),
                "outlier_fields": [
                    t["column"] for t in tlog.get("transformations", [])
                    if t.get("transformation") == "outlier_detection"
                ],
                "missing_value_summary": {
                    col: v["pct_missing"]
                    for col, v in tlog.get("missing_value_profile", {}).items()
                    if v["pct_missing"] > 0
                },
                "scope_included_count": scope_included_count,
                "scope_excluded_count": scope_excluded_count,
            }
        except Exception as e:
            result["layers"]["silver"] = {"available": False, "error": str(e)}
    else:
        result["layers"]["silver"] = {"available": False, "note": "Not yet processed (run Phase 3)"}

    # Gold
    from app.pipeline import load_gold
    try:
        gdf = load_gold(project_id, dataset, run_id)
        n_valid = int((gdf["row_status"] == "valid").sum()) if "row_status" in gdf.columns else None
        n_review = int((gdf["row_status"] == "needs_review").sum()) if "row_status" in gdf.columns else None
        n_invalid = int((gdf["row_status"] == "invalid").sum()) if "row_status" in gdf.columns else None
        result["layers"]["gold"] = {
            "row_count": len(gdf),
            "column_count": len(gdf.columns),
            "columns": list(gdf.columns),
            "sample": json.loads(gdf.head(min(5, limit)).to_json(orient="records", date_format="iso")),
            "available": True,
            "row_status_counts": {"valid": n_valid, "needs_review": n_review, "invalid": n_invalid},
        }
    except FileNotFoundError:
        result["layers"]["gold"] = {"available": False, "note": "Not yet validated (run Phase 3 to completion)"}
    except Exception as e:
        result["layers"]["gold"] = {"available": False, "error": str(e)}

    return result


@app.get("/config/canonical-fields/{dataset}")
def canonical_fields(dataset: str):
    """Return the canonical field names defined for a specific dataset (for mapping dropdowns)."""
    from app.config import load_canonical_schema
    try:
        schema = load_canonical_schema(dataset)
        return {"dataset": dataset, "fields": schema.field_names}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No canonical schema found for dataset '{dataset}'")


# ---------------------------------------------------------------------------
# Scope Filters — user-defined business scope rules per dataset
# (separate from data-quality validation; controls what counts toward
#  downstream business analysis / KPIs, without ever dropping raw records)
# ---------------------------------------------------------------------------

class ScopeRule(BaseModel):
    id: Optional[str] = None
    type: str  # date_range | include_values | exclude_values | numeric_range
    field: str
    description: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    values: Optional[list] = None
    min: Optional[float] = None
    max: Optional[float] = None


class SaveScopeRulesRequest(BaseModel):
    rules: List[ScopeRule]


@app.get("/scope-filters/{project_id}")
def get_scope_filters(project_id: str):
    """Return all configured scope rules for a project, grouped by dataset."""
    from app.scope_filter import load_scope_filters
    return {"project_id": project_id, "rules": load_scope_filters(project_id)}


@app.get("/scope-filters/{project_id}/{dataset}")
def get_dataset_scope_filters(project_id: str, dataset: str):
    from app.scope_filter import get_dataset_scope_rules
    return {"project_id": project_id, "dataset": dataset, "rules": get_dataset_scope_rules(project_id, dataset)}


@app.post("/scope-filters/{project_id}/{dataset}")
def save_scope_filters(project_id: str, dataset: str, req: SaveScopeRulesRequest):
    """Replace the full scope rule list for a dataset. Rules take effect on the
    next pipeline run (Phase 3 / full pipeline) — existing Gold data is unaffected
    until re-validated."""
    from app.scope_filter import save_dataset_scope_rules, RULE_TYPES
    for r in req.rules:
        if r.type not in RULE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid rule type '{r.type}'. Must be one of {RULE_TYPES}")
    rules_dicts = [r.dict(exclude_none=True) for r in req.rules]
    save_dataset_scope_rules(project_id, dataset, rules_dicts)
    return {"status": "saved", "dataset": dataset, "rule_count": len(rules_dicts)}


@app.get("/runs/{project_id}/{run_id}/scope-summary")
def scope_summary_all(project_id: str, run_id: str):
    """Per-dataset summary of in-scope vs excluded record counts + top exclusion reasons."""
    from app.scope_filter import scope_summary
    result = {}
    for dataset in DATASETS:
        try:
            df = load_gold(project_id, dataset, run_id)
            result[dataset] = scope_summary(df)
        except FileNotFoundError:
            result[dataset] = {"total": 0, "included": 0, "excluded": 0, "pct_excluded": 0.0, "reasons": {}}
    return {"project_id": project_id, "run_id": run_id, "datasets": result}


@app.get("/runs/{project_id}/{run_id}/excluded/{dataset}")
def excluded_records(project_id: str, run_id: str, dataset: str, limit: int = 500):
    """List of records excluded from business scope for this dataset/run, with reasons."""
    try:
        df = load_gold(project_id, dataset, run_id)
    except FileNotFoundError:
        return {"dataset": dataset, "count": 0, "records": []}
    if "scope_included" not in df.columns:
        return {"dataset": dataset, "count": 0, "records": []}
    excluded_df = df[~df["scope_included"]]
    return {"dataset": dataset, "count": len(excluded_df), "records": _df_to_records(excluded_df.head(limit))}
