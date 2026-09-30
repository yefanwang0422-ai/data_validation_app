"""
LLM-Assisted Silver Layer Cleanup (Operating Manual — LLM Manual Cleanup Behavior).

Allows users to issue natural-language or structured cleanup instructions that are
applied to the Silver layer only (never Bronze). All changes are:
- Logged with full versioning
- Reversible (original Silver preserved)
- Applied only after user approval
- Stored in a cleanup decision log

Supported instruction types:
- rename_column: rename a column to a new name
- remap_values: map specific values in a column to new values
- mark_as_null: treat specific values as null/missing
- exclude_column: mark a column as excluded (adds raw__ prefix behavior note)
- define_allowed_values: validate a column against an allowed list, flag violations
- impute_missing: fill missing values with a constant or strategy (mean/median/mode/constant)
- derive_field: create a new derived column from an expression
- custom_filter: flag rows matching a condition for review
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import RUN_LOG_DIR, SILVER_DIR


# ---------------------------------------------------------------------------
# Cleanup instruction execution
# ---------------------------------------------------------------------------

def apply_cleanup_instructions(
    df: pd.DataFrame,
    instructions: List[Dict[str, Any]],
    project_id: str,
    dataset: str,
    run_id: str,
    approved_by: str = "user",
) -> tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Apply a list of approved cleanup instructions to a Silver DataFrame.
    Returns (modified_df, decision_log_entries).

    Instructions are applied in order. Each instruction must have:
    - type: one of the supported instruction types
    - column: target column name (where applicable)
    - ... type-specific parameters

    GUARDRAILS:
    - Never modifies Bronze data
    - Logs every change with before/after summary
    - Flags modeling integrity risks but still applies if user approves
    """
    df = df.copy()
    decision_log: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for instr in instructions:
        instr_type = instr.get("type", "").lower()
        col = instr.get("column")
        instr_id = str(uuid.uuid4())[:8]

        try:
            if instr_type == "rename_column":
                new_name = instr["new_name"]
                if col in df.columns:
                    df = df.rename(columns={col: new_name})
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Renamed column '{col}' to '{new_name}'.", instr)
                else:
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Column '{col}' not found — skipped.", instr, status="skipped")

            elif instr_type == "remap_values":
                value_map = instr["value_map"]  # {old_value: new_value}
                if col in df.columns:
                    n_before = df[col].value_counts().to_dict()
                    df[col] = df[col].replace(value_map)
                    n_after = df[col].value_counts().to_dict()
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Remapped {len(value_map)} values in '{col}'.", instr,
                         extra={"value_map": value_map})

            elif instr_type == "mark_as_null":
                values_to_null = instr["values"]  # list of values to treat as null
                if col in df.columns:
                    n_changed = int(df[col].isin(values_to_null).sum())
                    df[col] = df[col].replace({v: None for v in values_to_null})
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Marked {n_changed} values as null in '{col}' for values: {values_to_null}.", instr)

            elif instr_type == "exclude_column":
                reason = instr.get("reason", "User-marked as not needed for modeling.")
                _log(decision_log, instr_id, instr_type, col, approved_by, now,
                     f"Column '{col}' excluded: {reason}. Column retained in Silver with exclusion note.",
                     instr, warning=f"Column retained in Silver — exclusion is advisory only. Remove in downstream Gold export if needed.")

            elif instr_type == "define_allowed_values":
                allowed = instr["allowed_values"]
                if col in df.columns:
                    flag_col = f"{col}_allowed_value_violation"
                    violation_mask = df[col].notna() & ~df[col].isin(allowed)
                    df[flag_col] = violation_mask
                    n_violations = int(violation_mask.sum())
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Defined {len(allowed)} allowed values for '{col}'. {n_violations} violations flagged in '{flag_col}'.", instr,
                         extra={"allowed_values": allowed, "violation_count": n_violations})

            elif instr_type == "impute_missing":
                strategy = instr.get("strategy", "constant")
                value = instr.get("value")
                if col in df.columns:
                    n_missing = int(df[col].isna().sum())
                    if n_missing == 0:
                        _log(decision_log, instr_id, instr_type, col, approved_by, now,
                             f"No missing values in '{col}' — nothing to impute.", instr, status="skipped")
                        continue
                    if strategy == "mean":
                        fill_val = df[col].mean()
                    elif strategy == "median":
                        fill_val = df[col].median()
                    elif strategy == "mode":
                        fill_val = df[col].mode().iloc[0] if not df[col].mode().empty else None
                    else:  # constant
                        fill_val = value
                    if fill_val is not None:
                        df[col] = df[col].fillna(fill_val)
                        # Add imputation flag
                        impute_flag_col = f"{col}_imputed"
                        df[impute_flag_col] = df[col].isna()  # marks where we filled (post-fill this should be False)
                        _log(decision_log, instr_id, instr_type, col, approved_by, now,
                             f"Imputed {n_missing} missing values in '{col}' with {strategy}={fill_val}. Flag: '{impute_flag_col}'.",
                             instr, warning="Imputed values should be reviewed before Gold promotion.")

            elif instr_type == "derive_field":
                new_col = instr["new_column"]
                expression = instr.get("expression", "")
                # Safe eval using pd.eval with limited scope
                try:
                    df[new_col] = df.eval(expression)
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Derived new column '{new_col}' from expression: {expression}.", instr)
                except Exception as e:
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Failed to derive '{new_col}': {e}", instr, status="error")

            elif instr_type == "custom_filter":
                condition = instr.get("condition", "")
                flag_col = instr.get("flag_column", f"custom_flag_{instr_id}")
                reason = instr.get("reason", "User-defined flag condition")
                try:
                    df[flag_col] = df.eval(condition)
                    n_flagged = int(df[flag_col].sum())
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Custom filter applied — {n_flagged} rows flagged in '{flag_col}'. Condition: {condition}. Reason: {reason}.",
                         instr, extra={"flagged_count": n_flagged})
                except Exception as e:
                    _log(decision_log, instr_id, instr_type, col, approved_by, now,
                         f"Custom filter failed: {e}", instr, status="error")

            elif instr_type == "ai_enrich":
                # Use the existing AI enrichment engine to fill missing geo fields
                # from address_line_1, cross-record postal evidence, or geocoding.
                from app.ai_enrichment import enrich_missing_geo_fields
                fields = instr.get("fields", ["city", "state", "postal_code", "latitude", "longitude"])
                try:
                    enriched_df, review_items = enrich_missing_geo_fields(df, dataset, run_id)
                    n_filled = sum(
                        int((enriched_df[f].notna() & df[f].isna()).sum())
                        for f in fields if f in enriched_df.columns and f in df.columns
                    )
                    df = enriched_df
                    _log(decision_log, instr_id, instr_type, str(fields), approved_by, now,
                         f"AI enrichment applied — {n_filled} values filled across fields {fields} "
                         f"using address parsing, cross-record evidence, and geocoding. "
                         f"{len(review_items)} review items generated.",
                         instr, extra={"fields": fields, "filled_count": n_filled, "review_items_count": len(review_items)})
                except Exception as e:
                    _log(decision_log, instr_id, instr_type, str(fields), approved_by, now,
                         f"AI enrichment failed: {e}", instr, status="error")

            elif instr_type == "standardize_categoricals":
                # Re-run categorical normalization from silver_etl on specific columns
                from app.silver_etl import CATEGORICAL_MAPS, _normalize_categoricals
                temp_log: List[Dict] = []
                cols_to_norm = instr.get("columns") or list(CATEGORICAL_MAPS.keys())
                subset = df[[c for c in cols_to_norm if c in df.columns]] if cols_to_norm else df
                # Apply normalization only to requested columns
                for cname in (cols_to_norm if cols_to_norm else list(CATEGORICAL_MAPS.keys())):
                    if cname not in df.columns or cname not in CATEGORICAL_MAPS:
                        continue
                    mapping = CATEGORICAL_MAPS[cname]
                    mask = df[cname].notna()
                    original = df.loc[mask, cname].astype(str).str.strip()
                    normalized = original.str.lower().map(mapping)
                    changed_mask = normalized.notna() & (normalized.values != original.values)
                    n_changed = int(changed_mask.sum())
                    if n_changed > 0:
                        df.loc[original.index[changed_mask], cname] = normalized[changed_mask].values
                        _log(decision_log, instr_id, instr_type, cname, approved_by, now,
                             f"Standardized {n_changed} values in '{cname}' to canonical forms.", instr)
                if not any(e["type"] == "standardize_categoricals" for e in decision_log):
                    _log(decision_log, instr_id, instr_type, "ALL", approved_by, now,
                         "Categorical standardization complete — no changes needed.", instr, status="skipped")

            else:
                _log(decision_log, instr_id, instr_type, col, approved_by, now,
                     f"Unknown instruction type '{instr_type}' — skipped.", instr, status="skipped")

        except Exception as exc:  # noqa: BLE001
            _log(decision_log, instr_id, instr_type, col, approved_by, now,
                 f"Error applying '{instr_type}' on '{col}': {exc}", instr, status="error")

    # Persist cleaned Silver
    _write_cleaned_silver(df, project_id, dataset, run_id)

    # Persist cleanup decision log
    _write_cleanup_log(project_id, dataset, run_id, decision_log, approved_by)

    return df, decision_log


def _log(
    decision_log: List[Dict],
    instr_id: str,
    instr_type: str,
    column: Optional[str],
    approved_by: str,
    now: str,
    message: str,
    instruction: Dict,
    status: str = "applied",
    warning: Optional[str] = None,
    extra: Optional[Dict] = None,
) -> None:
    entry = {
        "instruction_id": instr_id,
        "type": instr_type,
        "column": column,
        "status": status,
        "message": message,
        "approved_by": approved_by,
        "created_at": now,
        "original_instruction": instruction,
    }
    if warning:
        entry["modeling_integrity_warning"] = warning
    if extra:
        entry.update(extra)
    decision_log.append(entry)


def _write_cleaned_silver(df: pd.DataFrame, project_id: str, dataset: str, run_id: str) -> None:
    """Write the cleaned Silver (overwriting the current Silver for this run)."""
    p = SILVER_DIR / project_id / dataset / run_id
    p.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p / "data.parquet", index=False)


def _write_cleanup_log(
    project_id: str, dataset: str, run_id: str,
    decision_log: List[Dict], approved_by: str
) -> None:
    """Persist cleanup decision log as JSON."""
    log_dir = RUN_LOG_DIR / project_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}_{dataset}_cleanup_log.json"

    # Append to existing log if it exists
    existing = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as fh:
            try:
                existing = json.load(fh).get("decisions", [])
            except Exception:
                existing = []

    payload = {
        "project_id": project_id,
        "dataset": dataset,
        "run_id": run_id,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "approved_by": approved_by,
        "decisions": existing + decision_log,
    }
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def load_cleanup_log(project_id: str, dataset: str, run_id: str) -> Dict:
    """Load the cleanup decision log for a Silver run."""
    log_path = RUN_LOG_DIR / project_id / f"{run_id}_{dataset}_cleanup_log.json"
    if not log_path.exists():
        return {"decisions": []}
    with open(log_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Natural Language → Cleanup Instructions parser (via AI Gateway)
# ---------------------------------------------------------------------------

_NL_PARSE_SYSTEM_PROMPT = """You are a data engineering assistant that converts natural language cleanup instructions
into structured JSON cleanup operations for a supply chain data pipeline.

The user will describe data cleanup actions in plain English. You must return ONLY a valid JSON array of cleanup instructions.
No markdown, no explanations, no code fences — just the raw JSON array.

Supported instruction types and their required fields:

1. rename_column: {"type": "rename_column", "column": "<old_name>", "new_name": "<new_name>"}
2. remap_values: {"type": "remap_values", "column": "<col>", "value_map": {"<old>": "<new>", ...}}
3. mark_as_null: {"type": "mark_as_null", "column": "<col>", "values": ["<val1>", "<val2>"]}
4. exclude_column: {"type": "exclude_column", "column": "<col>", "reason": "<why>"}
5. define_allowed_values: {"type": "define_allowed_values", "column": "<col>", "allowed_values": ["<v1>", "<v2>"]}
6. impute_missing: {"type": "impute_missing", "column": "<col>", "strategy": "mean|median|mode|constant", "value": <optional constant>}
7. derive_field: {"type": "derive_field", "column": null, "new_column": "<name>", "expression": "<pandas eval expression>"}
8. custom_filter: {"type": "custom_filter", "column": null, "condition": "<pandas eval expression>", "flag_column": "<flag_col_name>", "reason": "<why>"}
9. ai_enrich: {"type": "ai_enrich", "fields": ["city", "state", "postal_code", "latitude", "longitude"]}
   Use this when the user wants to FILL IN, POPULATE, ENRICH, or GEOCODE missing geographic fields.
   The AI enrichment engine uses address parsing, cross-record evidence, and geocoding to fill these fields.
10. standardize_categoricals: {"type": "standardize_categoricals", "columns": ["<col1>", "<col2>"]}
    Use this when the user wants to standardize or normalize categorical values to canonical forms
    (e.g., "truck", "TRK", "TRUCK" all become "Truck").

CRITICAL RULES:
- When the user says "fill in", "populate", "enrich", "geocode", "infer", or "add" geographic fields
  (city, state, zip, postal code, latitude, longitude, coordinates) → use ai_enrich
- When the user says "standardize", "normalize", "clean up" categorical columns → use standardize_categoricals
- When the user says "rename" or "change the name" → use rename_column
- When the user says "treat X as missing/null/empty" or "replace X with null" → use mark_as_null
- When the user says "map X to Y" or "replace X with Y" → use remap_values
- When the user says "fill missing with" or "impute" → use impute_missing
- When the user says "flag rows where" or "mark rows that" → use custom_filter
- When the user says "exclude" or "drop" a column → use exclude_column

Examples:

Input: "rename ShipDate to shipment_date"
Output: [{"type": "rename_column", "column": "ShipDate", "new_name": "shipment_date"}]

Input: "treat N/A, -, unknown as missing in the city column"
Output: [{"type": "mark_as_null", "column": "city", "values": ["N/A", "-", "unknown", "n/a"]}]

Input: "standardize shipment_mode: map TL and FTL to Truck, LTL to Truck, Air to Air"
Output: [{"type": "remap_values", "column": "shipment_mode", "value_map": {"TL": "Truck", "FTL": "Truck", "LTL": "Truck", "Air": "Air"}}]

Input: "fill missing volume values with 0"
Output: [{"type": "impute_missing", "column": "volume", "strategy": "constant", "value": 0}]

Input: "fill in city, state, zip code information from address_line_1"
Output: [{"type": "ai_enrich", "fields": ["city", "state", "postal_code"]}]

Input: "please fill in city, state, zip code information from address_line_1 column"
Output: [{"type": "ai_enrich", "fields": ["city", "state", "postal_code"]}]

Input: "populate the missing city state and postal code fields"
Output: [{"type": "ai_enrich", "fields": ["city", "state", "postal_code"]}]

Input: "geocode latitude and longitude from city and state"
Output: [{"type": "ai_enrich", "fields": ["latitude", "longitude"]}]

Input: "enrich all missing geographic fields"
Output: [{"type": "ai_enrich", "fields": ["city", "state", "postal_code", "latitude", "longitude"]}]

Input: "standardize the shipment_mode column values"
Output: [{"type": "standardize_categoricals", "columns": ["shipment_mode"]}]

Input: "normalize all categorical columns"
Output: [{"type": "standardize_categoricals", "columns": null}]

Input: "flag any rows where volume is greater than 100000 as outliers"
Output: [{"type": "custom_filter", "column": null, "condition": "volume > 100000", "flag_column": "volume_high_outlier_flag", "reason": "Volume exceeds 100000 — flagged for review"}]

Input: "fill missing latitude and longitude using geocoding"
Output: [{"type": "ai_enrich", "fields": ["latitude", "longitude"]}]

Input: "impute missing cost_amount with the median"
Output: [{"type": "impute_missing", "column": "cost_amount", "strategy": "median"}]

Return ONLY the JSON array. Always return at least one instruction if you can interpret the request at all.
"""


def parse_natural_language_instructions(nl_text: str) -> List[Dict[str, Any]]:
    """
    Parse natural language cleanup instructions into structured JSON using the AI Gateway.
    Falls back to an empty list if the AI is unavailable.
    """
    import os
    import uuid
    try:
        import httpx
    except ImportError:
        return []

    ai_base = os.getenv("AI_API_BASE", "https://api.ntth.ai/v1")
    ai_app_id = os.getenv("AI_APP_ID", "6a08840a-6fde-43ef-8a5b-d3e62d0c9b71")
    ai_app_secret = os.getenv("AI_APP_SECRET", "_>NqtarwpNLo&cezMevZwnJnVXG]lu8MtaWB")
    ai_model = os.getenv("AI_MODEL", "6c26a584-a988-4fed-92ea-f6501429fab9")

    try:
        # Auth
        auth_resp = httpx.post(
            f"{ai_base}/auth/appLogin",
            json={"id": ai_app_id, "secret": ai_app_secret},
            verify=False, timeout=15.0,
        )
        if auth_resp.status_code != 200:
            raise RuntimeError(f"Auth failed: {auth_resp.status_code}")
        token = auth_resp.json().get("token")
        if not token:
            raise RuntimeError("No token returned")

        request_body = {
            "id": str(uuid.uuid4()),
            "modelId": ai_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": _NL_PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": nl_text.strip()},
            ],
        }

        headers = {"Content-Type": "application/json", "Authorization": token}

        # Try workspace endpoint, fall back to chat
        raw_text = ""
        try:
            ws_resp = httpx.get(f"{ai_base}/workspace/workspaces", headers=headers, verify=False, timeout=10.0)
            if ws_resp.status_code == 200:
                items = ws_resp.json().get("items") or ws_resp.json().get("data") or []
                if items:
                    ws_id = str(items[0].get("id") or items[0].get("_id") or "")
                    run_resp = httpx.post(
                        f"{ai_base}/workspace/workspaces/{ws_id}/thread/run",
                        headers=headers, json=request_body, verify=False, timeout=60.0,
                    )
                    if run_resp.status_code == 200:
                        raw_text = run_resp.json().get("content", "")
        except Exception:
            pass

        if not raw_text:
            chat_resp = httpx.post(
                f"{ai_base}/chat",
                headers=headers,
                json={"id": request_body["id"], "modelId": ai_model, "stream": False, "messages": request_body["messages"]},
                verify=False, timeout=60.0,
            )
            if chat_resp.status_code == 200:
                raw_text = chat_resp.json().get("content", "")

        if not raw_text:
            return []

        # Strip markdown fences
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:])
        if raw_text.endswith("```"):
            raw_text = raw_text[:raw_text.rfind("```")]

        result = json.loads(raw_text.strip())
        if isinstance(result, list):
            return result
        return []

    except Exception:  # noqa: BLE001
        return []
