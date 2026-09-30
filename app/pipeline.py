"""
Pipeline Orchestrator (plan_v2.md Section 1 orchestration + Sections 0-6, 10).

Runs the full Bronze -> Silver -> Scope Filter -> Profile -> Validate ->
Cross-reference -> AI-enrich -> Gold flow across whichever datasets actually
have a configured data source (SQL query or uploaded file) for this project.
Datasets with no configured source are skipped entirely rather than causing
a failure -- the app works with whatever data is available.

Scope filtering order (per user requirement):
1. Bronze -> Silver (canonical mapping applied)
2. Scope filters applied immediately to Silver -- masters first, then
   transactionals. Master-data exclusions cascade automatically to any
   transactional row referencing an excluded master key (e.g., excluding
   Product A in product_master cascades exclusion to every shipment_history /
   production_history / inventory_history row referencing Product A), with a
   clear "Excluded via cascade" reason. The dataset is effectively "refreshed"
   at this point -- everything downstream (Profiling, Validation, AI
   enrichment, Gold) operates on this scope-aware Silver data.
3. Profiling / Validation / Cross-reference / AI enrichment / Gold as before.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from app.ai_enrichment import enrich_missing_geo_fields
from app.config import (
    DATASETS,
    GOLD_DIR,
    MASTER_DATASETS,
    RUN_LOG_DIR,
    TRANSACTIONAL_DATASETS,
    load_data_source_registry,
    new_run_id,
)
from app.scope_filter import apply_cascade_exclusions, apply_scope_filters, build_excluded_key_lookup
from app.extraction import (
    extract_dataset_from_sql_config,
    extract_dataset_from_uploaded_file,
    land_dataframe_to_bronze,
    load_bronze,
    load_extraction_config,
    sql_extraction_is_configured,
)
from app.profiling import run_profiling
from app.sample_data import generate_all_sample_data
from app.silver_etl import bronze_to_silver, load_silver
from app.validation import cross_reference_check, flag_in_scope_products, flag_in_scope_products_extended, validate_dataset

GEO_ENRICHABLE_DATASETS = {"customer_master", "location_master", "vendor_master"}


def _apply_scope_with_cascade(
    silver_frames: Dict[str, pd.DataFrame], project_id: str
) -> Dict[str, pd.DataFrame]:
    """
    Apply scope filters to Silver frames right after Bronze->Silver, refreshing
    the dataset before Profiling/Validation continue.

    Order:
    1. Apply each master dataset's own direct scope rules.
    2. Build a lookup of excluded master keys (e.g., excluded product_ids).
    3. Apply each transactional dataset's own direct scope rules, then cascade
       master exclusions onto it via foreign-key relationships (product_id,
       location_id, customer_id, vendor_id, etc.) — a transactional row whose
       FK points to an excluded master record is also marked excluded, with a
       clear "Excluded via cascade" reason, without overwriting a more
       specific direct-rule exclusion reason if one already applies.
    """
    result: Dict[str, pd.DataFrame] = dict(silver_frames)

    # Step 1: masters first
    for dataset in MASTER_DATASETS:
        if dataset in result:
            result[dataset] = apply_scope_filters(result[dataset], dataset, project_id)

    # Step 2: build excluded-key lookup from scoped masters
    master_frames_for_lookup = {d: result[d] for d in MASTER_DATASETS if d in result}
    excluded_key_lookup = build_excluded_key_lookup(master_frames_for_lookup)

    # Step 3: transactionals -- own rules, then cascade
    for dataset in TRANSACTIONAL_DATASETS:
        if dataset not in result:
            continue
        result[dataset] = apply_scope_filters(result[dataset], dataset, project_id)
        result[dataset] = apply_cascade_exclusions(result[dataset], dataset, excluded_key_lookup)

    return result


# ---------------------------------------------------------------------------
# Phase 1: Extract to Bronze only (returns run_id + raw column preview)
# ---------------------------------------------------------------------------

def extract_to_bronze(
    project_id: str,
    use_sample_data: Optional[bool] = None,
) -> Dict[str, object]:
    """
    Phase 1 of the 3-phase workflow: extract raw data into Bronze and
    auto-run column mapping suggestion (but do NOT yet apply the mapping
    or run Silver/Validation/Profiling).

    Returns a summary with:
      - run_id (used by Phase 3 to continue the same run)
      - per-dataset raw column names (for mapping review)
      - per-dataset row counts
      - extraction errors (if any)
    """
    from app.column_mapping import run_mapping_suggestion_for_dataset

    run_id = new_run_id()
    summary: Dict[str, object] = {
        "run_id": run_id,
        "project_id": project_id,
        "phase": "extracted",
        "datasets": {},
        "skipped_datasets": [],
        "extraction_errors": {},
    }

    dataset_sources = _resolve_active_datasets(project_id, use_sample_data)
    active_datasets = [ds for ds, src in dataset_sources.items() if src != "skip"]
    skipped_datasets = [ds for ds, src in dataset_sources.items() if src == "skip"]

    summary["dataset_sources"] = dataset_sources
    summary["skipped_datasets"] = skipped_datasets

    if dataset_sources and all(v == "sample" for v in dataset_sources.values() if v != "skip") and active_datasets:
        raw_frames = generate_all_sample_data()
        for dataset in active_datasets:
            land_dataframe_to_bronze(raw_frames[dataset], dataset, run_id, project_id, source="sample")
    else:
        failed_extraction: list = []
        sample_frames_cache: Optional[dict] = None
        for dataset in active_datasets:
            src = dataset_sources[dataset]
            if src == "sample":
                if sample_frames_cache is None:
                    sample_frames_cache = generate_all_sample_data()
                land_dataframe_to_bronze(sample_frames_cache[dataset], dataset, run_id, project_id, source="sample")
            elif src == "sql":
                result = extract_dataset_from_sql_config(dataset, run_id, project_id)
                if not result.success:
                    failed_extraction.append((dataset, f"SQL extraction failed: {result.error}"))
                    summary["dataset_sources"][dataset] = "skip"
                    skipped_datasets.append(dataset)
            elif src == "file":
                result = extract_dataset_from_uploaded_file(dataset, run_id, project_id)
                if not result.success:
                    failed_extraction.append((dataset, f"File extraction failed: {result.error}"))
                    summary["dataset_sources"][dataset] = "skip"
                    skipped_datasets.append(dataset)
        for dataset, reason in failed_extraction:
            active_datasets.remove(dataset)
            summary["extraction_errors"][dataset] = reason

    for ds in skipped_datasets:
        reason = summary["extraction_errors"].get(ds, "No data source configured.")
        summary["datasets"][ds] = {"skipped": True, "reason": reason}

    # After Bronze landing, ALWAYS regenerate the mapping suggestion from the
    # actual raw columns of this extraction (overwrite=True) so that stale
    # configs from earlier runs / different file schemas never hide columns.
    raw_column_preview: Dict[str, list] = {}
    for dataset in active_datasets:
        try:
            raw_df = load_bronze(project_id, dataset, run_id)
            run_mapping_suggestion_for_dataset(project_id, dataset, raw_df, overwrite=True)  # always fresh
            raw_column_preview[dataset] = list(raw_df.columns)
            summary["datasets"][dataset] = {
                "row_count": len(raw_df),
                "raw_columns": list(raw_df.columns),
                "skipped": False,
            }
        except Exception as exc:  # noqa: BLE001
            summary["datasets"][dataset] = {"skipped": True, "reason": str(exc)}

    summary["raw_column_preview"] = raw_column_preview

    # Save partial run summary to disk so Phase 3 can read it
    summary_path = RUN_LOG_DIR / project_id / f"{run_id}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    return summary


# ---------------------------------------------------------------------------
# Phase 3: Silver → Scope Filter → Profile → Validate → Enrich → Gold
# ---------------------------------------------------------------------------

def bronze_to_gold(
    project_id: str,
    run_id: str,
) -> Dict[str, object]:
    """
    Phase 3 of the 3-phase workflow: continue a run whose Bronze data was
    already extracted (via extract_to_bronze or a prior full-pipeline run).
    Applies the confirmed column mappings, refreshes the dataset with Scope
    Filters (including master->transactional cascade) immediately after
    Silver is produced, then runs Profile/Validate/Enrich/Gold on the
    scope-aware data.

    This is called after the user has reviewed and approved column mappings
    in Phase 2.
    """
    # Load the partial summary from Phase 1
    summary_path = RUN_LOG_DIR / project_id / f"{run_id}_summary.json"
    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as fh:
            summary = json.load(fh)
    else:
        summary = {"run_id": run_id, "project_id": project_id, "datasets": {}}

    summary["phase"] = "completed"

    issue_log_path = RUN_LOG_DIR / project_id / f"{run_id}_issues.jsonl"
    review_queue_path = RUN_LOG_DIR / project_id / f"{run_id}_review_queue.jsonl"
    xref_exceptions_path = RUN_LOG_DIR / project_id / f"{run_id}_cross_reference_exceptions.jsonl"

    # Determine which datasets to process (those that have Bronze data)
    from app.config import BRONZE_DIR
    bronze_project = BRONZE_DIR / project_id
    active_datasets = []
    if bronze_project.exists():
        for ds in DATASETS:
            ds_path = bronze_project / ds / run_id / "data.parquet"
            if ds_path.exists():
                active_datasets.append(ds)

    # ---- Silver (per-dataset error capture) ----
    silver_frames: Dict[str, pd.DataFrame] = {}
    silver_errors: Dict[str, str] = {}
    for dataset in active_datasets:
        try:
            raw_df = load_bronze(project_id, dataset, run_id)
            silver_df = bronze_to_silver(raw_df, dataset, project_id, run_id)
            silver_frames[dataset] = silver_df
        except Exception as exc:  # noqa: BLE001
            error_msg = f"[{dataset}] Silver/ETL transformation failed: {exc}"
            silver_errors[dataset] = error_msg
            summary["datasets"][dataset] = {"skipped": True, "reason": error_msg}

    if silver_errors:
        summary["silver_errors"] = silver_errors

    # ---- Apply Scope Filters immediately after Silver ("refresh" the dataset) ----
    # Masters filtered first, then transactionals with cascade from excluded master keys.
    silver_frames = _apply_scope_with_cascade(silver_frames, project_id)

    # ---- Profiling (runs on the scope-refreshed Silver data) ----
    for dataset, silver_df in silver_frames.items():
        try:
            run_profiling(silver_df, project_id, dataset, run_id)
        except Exception as exc:  # noqa: BLE001
            summary.setdefault("profiling_errors", {})[dataset] = str(exc)

    active_masters = [d for d in MASTER_DATASETS if d in silver_frames]
    active_transactionals = [d for d in TRANSACTIONAL_DATASETS if d in silver_frames]

    # ---- Validation (masters first) ----
    gold_frames: Dict[str, pd.DataFrame] = {}
    all_issues = []
    for dataset in active_masters:
        try:
            gold_df, issues = validate_dataset(silver_frames[dataset], dataset, run_id)
            gold_frames[dataset] = gold_df
            all_issues.extend(issues)
        except Exception as exc:  # noqa: BLE001
            summary["datasets"][dataset] = {"skipped": True, "reason": f"[{dataset}] Validation failed: {exc}"}

    # AI enrichment
    all_review_items = []
    for dataset in GEO_ENRICHABLE_DATASETS.intersection(gold_frames.keys()):
        enriched, review_items = enrich_missing_geo_fields(gold_frames[dataset], dataset, run_id)
        gold_frames[dataset] = enriched
        all_review_items.extend(review_items)

    if "product_master" in gold_frames and "shipment_history" in silver_frames:
        gold_frames["product_master"] = flag_in_scope_products(
            gold_frames["product_master"], silver_frames["shipment_history"]
        )

    # ---- Transactionals ----
    all_xref_exceptions = []
    for dataset in active_transactionals:
        try:
            gold_df, issues = validate_dataset(silver_frames[dataset], dataset, run_id)
            all_issues.extend(issues)
            master_frames_for_xref = {m: gold_frames[m] for m in active_masters if m in gold_frames}
            if dataset == "shipment_cost" and "shipment_history" in gold_frames:
                master_frames_for_xref["shipment_history"] = gold_frames["shipment_history"]
            gold_df, xref_exceptions = cross_reference_check(gold_df, dataset, run_id, master_frames_for_xref)
            all_xref_exceptions.extend(xref_exceptions)
            gold_frames[dataset] = gold_df
        except Exception as exc:  # noqa: BLE001
            summary["datasets"][dataset] = {"skipped": True, "reason": f"[{dataset}] Validation/cross-reference failed: {exc}"}

    # ---- Carry scope columns (computed on Silver) through to Gold ----
    for dataset in list(gold_frames.keys()):
        silver_df = silver_frames.get(dataset)
        if silver_df is not None and "scope_included" in silver_df.columns:
            gold_frames[dataset]["scope_included"] = silver_df["scope_included"].values
            gold_frames[dataset]["scope_exclusion_reason"] = silver_df["scope_exclusion_reason"].values
        elif "scope_included" not in gold_frames[dataset].columns:
            gold_frames[dataset]["scope_included"] = True
            gold_frames[dataset]["scope_exclusion_reason"] = None

    # ---- Persist Gold ----
    for dataset in active_datasets:
        if dataset not in gold_frames:
            continue
        _write_gold(gold_frames[dataset], project_id, dataset, run_id)
        n_valid = int((gold_frames[dataset]["row_status"] == "valid").sum())
        n_review = int((gold_frames[dataset]["row_status"] == "needs_review").sum())
        n_invalid = int((gold_frames[dataset]["row_status"] == "invalid").sum())
        n_scope_excluded = int((~gold_frames[dataset]["scope_included"]).sum()) if "scope_included" in gold_frames[dataset].columns else 0
        summary["datasets"][dataset] = {
            "row_count": len(gold_frames[dataset]),
            "valid": n_valid,
            "needs_review": n_review,
            "invalid": n_invalid,
            "scope_excluded": n_scope_excluded,
            "skipped": False,
        }

    _append_jsonl(issue_log_path, all_issues)
    _append_jsonl(review_queue_path, all_review_items)
    _append_jsonl(xref_exceptions_path, all_xref_exceptions)

    summary["issue_count"] = len(all_issues)
    summary["review_queue_count"] = len(all_review_items)
    summary["cross_reference_exception_count"] = len(all_xref_exceptions)
    summary["extraction_source"] = summary.get("extraction_source", "mixed")

    # Update saved summary
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    return summary


def _gold_path(project_id: str, dataset: str, run_id: str) -> Path:
    p = GOLD_DIR / project_id / dataset / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "data.parquet"


def _write_gold(df: pd.DataFrame, project_id: str, dataset: str, run_id: str) -> None:
    df.to_parquet(_gold_path(project_id, dataset, run_id), index=False)


def load_gold(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    path = _gold_path(project_id, dataset, run_id)
    if not path.exists():
        raise FileNotFoundError(f"No gold data found for {project_id}/{dataset}/{run_id}")
    return pd.read_parquet(path)


def _append_jsonl(path: Path, records: list) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, default=str) + "\n")


def _resolve_active_datasets(project_id: str, use_sample_data: Optional[bool]) -> Dict[str, str]:
    """
    Determine, per dataset, which source to use this run:
      "sample" | "sql" | "file" | "skip"

    - If use_sample_data is True: every dataset uses sample data (demo mode).
    - If use_sample_data is False: only datasets with a configured SQL query are
      extracted via SQL; everything else is skipped (legacy explicit-SQL-only mode).
    - If use_sample_data is None (default, normal app usage): each dataset's
      source is resolved independently from its data source registry entry
      (sql / file / none) set on the Data Sources screen. Datasets set to
      "none" (or with no uploaded file / SQL configured) are skipped -- the
      app runs successfully with whatever data is actually available.
    """
    if use_sample_data is True:
        return {ds: "sample" for ds in DATASETS}

    registry = load_data_source_registry(project_id)
    sql_ready = sql_extraction_is_configured()
    sql_cfg = None
    if sql_ready:
        try:
            sql_cfg = load_extraction_config()
        except FileNotFoundError:
            sql_ready = False

    resolution: Dict[str, str] = {}
    for ds in DATASETS:
        entry = registry.get(ds, {"source_type": "none"})
        source_type = entry.get("source_type", "none")

        if use_sample_data is False:
            # Legacy explicit mode: only honor SQL-configured datasets.
            if sql_ready and sql_cfg and ds in sql_cfg.get("datasets", {}):
                resolution[ds] = "sql"
            else:
                resolution[ds] = "skip"
            continue

        if source_type == "sql" and sql_ready and sql_cfg and ds in sql_cfg.get("datasets", {}):
            resolution[ds] = "sql"
        elif source_type == "file":
            resolution[ds] = "file"
        else:
            resolution[ds] = "skip"

    # If literally nothing is configured anywhere, fall back to sample data so
    # the app remains usable out of the box / for demos.
    if all(v == "skip" for v in resolution.values()) and use_sample_data is None:
        return {ds: "sample" for ds in DATASETS}

    return resolution


def run_full_pipeline(
    project_id: str, use_sample_data: Optional[bool] = None
) -> Dict[str, object]:
    """
    Execute the pipeline for one run across whichever datasets have a
    configured data source. Returns a summary dict including per-dataset
    row counts (or skip reasons) and aggregate issue counts.
    """
    run_id = new_run_id()
    summary: Dict[str, object] = {"run_id": run_id, "project_id": project_id, "datasets": {}}

    issue_log_path = RUN_LOG_DIR / project_id / f"{run_id}_issues.jsonl"
    review_queue_path = RUN_LOG_DIR / project_id / f"{run_id}_review_queue.jsonl"
    xref_exceptions_path = RUN_LOG_DIR / project_id / f"{run_id}_cross_reference_exceptions.jsonl"

    # ---- Step 0: Resolve sources & Extraction (Bronze) ----
    dataset_sources = _resolve_active_datasets(project_id, use_sample_data)
    active_datasets = [ds for ds, src in dataset_sources.items() if src != "skip"]
    skipped_datasets = [ds for ds, src in dataset_sources.items() if src == "skip"]

    summary["dataset_sources"] = dataset_sources
    summary["skipped_datasets"] = skipped_datasets

    if dataset_sources and all(v == "sample" for v in dataset_sources.values() if v != "skip") and active_datasets:
        # Pure sample-data run (demo mode or nothing configured)
        raw_frames = generate_all_sample_data()
        for dataset in active_datasets:
            land_dataframe_to_bronze(raw_frames[dataset], dataset, run_id, project_id, source="sample")
    else:
        failed_extraction: list = []
        sample_frames_cache: Optional[dict] = None
        for dataset in active_datasets:
            src = dataset_sources[dataset]
            if src == "sample":
                if sample_frames_cache is None:
                    sample_frames_cache = generate_all_sample_data()
                land_dataframe_to_bronze(sample_frames_cache[dataset], dataset, run_id, project_id, source="sample")
            elif src == "sql":
                result = extract_dataset_from_sql_config(dataset, run_id, project_id)
                if not result.success:
                    failed_extraction.append((dataset, f"SQL extraction failed: {result.error}"))
                    summary["dataset_sources"][dataset] = "skip"
                    skipped_datasets.append(dataset)
            elif src == "file":
                result = extract_dataset_from_uploaded_file(dataset, run_id, project_id)
                if not result.success:
                    failed_extraction.append((dataset, f"File extraction failed: {result.error}"))
                    summary["dataset_sources"][dataset] = "skip"
                    skipped_datasets.append(dataset)
        # Remove failed extractions AFTER the loop to avoid modifying-while-iterating
        for dataset, reason in failed_extraction:
            active_datasets.remove(dataset)
            # Store extraction error in summary so the UI can display the root cause
            summary["extraction_errors"] = summary.get("extraction_errors", {})
            summary["extraction_errors"][dataset] = reason

    for ds in skipped_datasets:
        reason = summary.get("extraction_errors", {}).get(ds, "No data source configured.")
        summary["datasets"][ds] = {"skipped": True, "reason": reason}

    # ---- Step 1: Silver (active datasets only) ----
    silver_frames: Dict[str, pd.DataFrame] = {}
    for dataset in active_datasets:
        raw_df = load_bronze(project_id, dataset, run_id)
        silver_df = bronze_to_silver(raw_df, dataset, project_id, run_id)
        silver_frames[dataset] = silver_df

    # ---- Step 2: Apply Scope Filters immediately after Silver ("refresh" the dataset) ----
    # Masters filtered first, then transactionals with cascade from excluded master keys.
    silver_frames = _apply_scope_with_cascade(silver_frames, project_id)

    # ---- Step 3: Profiling (runs on the scope-refreshed Silver data) ----
    for dataset, silver_df in silver_frames.items():
        run_profiling(silver_df, project_id, dataset, run_id)

    active_masters = [d for d in MASTER_DATASETS if d in silver_frames]
    active_transactionals = [d for d in TRANSACTIONAL_DATASETS if d in silver_frames]

    # ---- Step 4-5: Validation (masters first, only those present) ----
    gold_frames: Dict[str, pd.DataFrame] = {}
    all_issues = []
    for dataset in active_masters:
        gold_df, issues = validate_dataset(silver_frames[dataset], dataset, run_id)
        gold_frames[dataset] = gold_df
        all_issues.extend(issues)

    # AI enrichment for geo-enrichable master datasets that are present
    all_review_items = []
    for dataset in GEO_ENRICHABLE_DATASETS.intersection(gold_frames.keys()):
        enriched, review_items = enrich_missing_geo_fields(gold_frames[dataset], dataset, run_id)
        gold_frames[dataset] = enriched
        all_review_items.extend(review_items)

    # Product master in-scope flagging: uses outbound_shipment_history or shipment_history
    if "product_master" in gold_frames:
        gold_frames["product_master"] = flag_in_scope_products_extended(
            gold_frames["product_master"], silver_frames
        )

    # ---- Transactional datasets: validate + cross-reference (present ones only) ----
    all_xref_exceptions = []
    for dataset in active_transactionals:
        gold_df, issues = validate_dataset(silver_frames[dataset], dataset, run_id)
        all_issues.extend(issues)

        # Only cross-check against master tables that are actually present this run.
        master_frames_for_xref = {m: gold_frames[m] for m in active_masters if m in gold_frames}
        if dataset == "shipment_cost" and "shipment_history" in gold_frames:
            master_frames_for_xref["shipment_history"] = gold_frames["shipment_history"]

        gold_df, xref_exceptions = cross_reference_check(gold_df, dataset, run_id, master_frames_for_xref)
        all_xref_exceptions.extend(xref_exceptions)
        gold_frames[dataset] = gold_df

    # ---- Carry scope columns (computed on Silver) through to Gold ----
    for dataset in list(gold_frames.keys()):
        silver_df = silver_frames.get(dataset)
        if silver_df is not None and "scope_included" in silver_df.columns:
            gold_frames[dataset]["scope_included"] = silver_df["scope_included"].values
            gold_frames[dataset]["scope_exclusion_reason"] = silver_df["scope_exclusion_reason"].values
        elif "scope_included" not in gold_frames[dataset].columns:
            gold_frames[dataset]["scope_included"] = True
            gold_frames[dataset]["scope_exclusion_reason"] = None

    # ---- Persist Gold + logs (active datasets only) ----
    for dataset in active_datasets:
        if dataset not in gold_frames:
            continue
        _write_gold(gold_frames[dataset], project_id, dataset, run_id)
        n_valid = int((gold_frames[dataset]["row_status"] == "valid").sum())
        n_review = int((gold_frames[dataset]["row_status"] == "needs_review").sum())
        n_invalid = int((gold_frames[dataset]["row_status"] == "invalid").sum())
        n_scope_excluded = int((~gold_frames[dataset]["scope_included"]).sum()) if "scope_included" in gold_frames[dataset].columns else 0
        summary["datasets"][dataset] = {
            "row_count": len(gold_frames[dataset]),
            "valid": n_valid,
            "needs_review": n_review,
            "invalid": n_invalid,
            "scope_excluded": n_scope_excluded,
            "skipped": False,
        }

    _append_jsonl(issue_log_path, all_issues)
    _append_jsonl(review_queue_path, all_review_items)
    _append_jsonl(xref_exceptions_path, all_xref_exceptions)

    summary["issue_count"] = len(all_issues)
    summary["review_queue_count"] = len(all_review_items)
    summary["cross_reference_exception_count"] = len(all_xref_exceptions)
    summary["extraction_source"] = (
        "sample"
        if all(v == "sample" for v in dataset_sources.values() if v != "skip") and active_datasets
        else "mixed"
    )

    # Save run summary
    summary_path = RUN_LOG_DIR / project_id / f"{run_id}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    return summary


def latest_run_id(project_id: str) -> str:
    """Find the most recent run_id for a project by scanning gold artifacts."""
    proj_gold = GOLD_DIR / project_id
    if not proj_gold.exists():
        raise FileNotFoundError(f"No gold data for project '{project_id}' yet.")
    run_ids = set()
    for dataset_dir in proj_gold.iterdir():
        if dataset_dir.is_dir():
            for run_dir in dataset_dir.iterdir():
                if run_dir.is_dir():
                    run_ids.add(run_dir.name)
    if not run_ids:
        raise FileNotFoundError(f"No runs found for project '{project_id}'.")
    return sorted(run_ids)[-1]
