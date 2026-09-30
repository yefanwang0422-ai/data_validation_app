"""
Scope Filter Engine — user-defined business scope rules per dataset/project.

Allows analysts to define WHICH records are "in scope" for downstream business
analysis (separate from data-quality validation status). For example:
- Only shipment_history records within a date range
- Only product_master records in certain categories
- Exclude specific vendor_ids

Records are NEVER dropped — every row is retained through the pipeline.
Instead, two new Gold columns are added:
- scope_included (bool): True if the record passes ALL scope rules for its dataset
- scope_exclusion_reason (str|None): human-readable description of the FIRST
  failing rule, or None if included

Rules are stored per-project, per-dataset, as JSON:
  configs/scope_filters/{project_id}.json
  {
    "shipment_history": [
      {"id": "...", "type": "date_range", "field": "shipment_date",
       "start": "2024-01-01", "end": "2024-12-31", "description": "2024 shipments only"},
      {"id": "...", "type": "include_values", "field": "product_category",
       "values": ["Electronics", "Chemicals"], "description": "In-scope categories"}
    ]
  }

Supported rule types:
- date_range: field must fall between start/end (inclusive). Missing dates fail the rule.
- include_values: field value must be in `values` list (case-insensitive string match)
- exclude_values: field value must NOT be in `values` list
- numeric_range: field must fall between min/max (inclusive). Missing values fail the rule.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import CONFIG_DIR

SCOPE_FILTER_DIR = CONFIG_DIR / "scope_filters"
SCOPE_FILTER_DIR.mkdir(parents=True, exist_ok=True)

RULE_TYPES = ("date_range", "include_values", "exclude_values", "numeric_range")


# ---------------------------------------------------------------------------
# Config load / save
# ---------------------------------------------------------------------------

def _scope_config_path(project_id: str) -> Path:
    return SCOPE_FILTER_DIR / f"{project_id}.json"


def load_scope_filters(project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return { dataset: [rule, ...] } for a project. Empty dict if none configured."""
    path = _scope_config_path(project_id)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_dataset_scope_rules(project_id: str, dataset: str, rules: List[Dict[str, Any]]) -> None:
    """Replace the full rule list for a dataset within a project's scope config."""
    all_rules = load_scope_filters(project_id)
    # Ensure every rule has an id
    for r in rules:
        if not r.get("id"):
            r["id"] = str(uuid.uuid4())[:8]
    all_rules[dataset] = rules
    path = _scope_config_path(project_id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(all_rules, fh, indent=2, default=str)


def get_dataset_scope_rules(project_id: str, dataset: str) -> List[Dict[str, Any]]:
    return load_scope_filters(project_id).get(dataset, [])


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def _evaluate_rule(df: pd.DataFrame, rule: Dict[str, Any]) -> pd.Series:
    """
    Returns a boolean Series (True = row PASSES this rule / stays in scope).
    Any error in rule config (missing field, bad values) fails safe -> returns
    all-True (does not incorrectly exclude data due to a config problem).
    """
    rule_type = rule.get("type")
    field = rule.get("field")

    if not field or field not in df.columns:
        return pd.Series([True] * len(df), index=df.index)

    try:
        if rule_type == "date_range":
            series = pd.to_datetime(df[field], errors="coerce")
            start = pd.to_datetime(rule.get("start")) if rule.get("start") else None
            end = pd.to_datetime(rule.get("end")) if rule.get("end") else None
            passes = series.notna()
            if start is not None:
                passes &= series >= start
            if end is not None:
                passes &= series <= end
            return passes

        elif rule_type == "include_values":
            allowed = set(str(v).strip().lower() for v in rule.get("values", []))
            if not allowed:
                return pd.Series([True] * len(df), index=df.index)
            series = df[field].astype(str).str.strip().str.lower()
            return series.isin(allowed)

        elif rule_type == "exclude_values":
            excluded = set(str(v).strip().lower() for v in rule.get("values", []))
            if not excluded:
                return pd.Series([True] * len(df), index=df.index)
            series = df[field].astype(str).str.strip().str.lower()
            return ~series.isin(excluded)

        elif rule_type == "numeric_range":
            series = pd.to_numeric(df[field], errors="coerce")
            min_v = rule.get("min")
            max_v = rule.get("max")
            passes = series.notna()
            if min_v is not None:
                passes &= series >= float(min_v)
            if max_v is not None:
                passes &= series <= float(max_v)
            return passes

    except Exception:  # noqa: BLE001
        return pd.Series([True] * len(df), index=df.index)

    return pd.Series([True] * len(df), index=df.index)


def apply_scope_filters(df: pd.DataFrame, dataset: str, project_id: str) -> pd.DataFrame:
    """
    Apply all configured scope rules for this dataset to the Gold DataFrame.
    Adds:
      - scope_included: bool (True if ALL rules pass)
      - scope_exclusion_reason: str|None (description of first failing rule)

    Rows are never dropped. If no rules are configured for this dataset,
    every row is marked scope_included=True with no exclusion reason.
    """
    df = df.copy()
    rules = get_dataset_scope_rules(project_id, dataset)

    if not rules:
        df["scope_included"] = True
        df["scope_exclusion_reason"] = None
        return df

    included = pd.Series([True] * len(df), index=df.index)
    exclusion_reason = pd.Series([None] * len(df), index=df.index, dtype=object)

    for rule in rules:
        rule_passes = _evaluate_rule(df, rule)
        newly_failed = included & ~rule_passes
        if newly_failed.any():
            desc = rule.get("description") or f"{rule.get('type')} rule on '{rule.get('field')}'"
            exclusion_reason.loc[newly_failed] = desc
        included &= rule_passes

    df["scope_included"] = included
    df["scope_exclusion_reason"] = exclusion_reason
    return df


# ---------------------------------------------------------------------------
# Cascade: master-data exclusions propagate to transactional datasets via FK
# ---------------------------------------------------------------------------

# Maps transactional dataset -> list of (fk_field, master_dataset, master_key_field)
# Mirrors app/validation.py CROSS_REFERENCE_RULES so cascade uses the same FK relationships.
CASCADE_FK_MAP: Dict[str, List[Dict[str, str]]] = {
    "shipment_history": [
        {"field": "product_id", "master": "product_master", "master_key": "product_id"},
        {"field": "origin_location_id", "master": "location_master", "master_key": "location_id"},
        {"field": "destination_location_id", "master": "customer_master", "master_key": "customer_id"},
    ],
    "inbound_shipment_history": [
        {"field": "product_id", "master": "product_master", "master_key": "product_id"},
        {"field": "origin_location_id", "master": "vendor_master", "master_key": "vendor_id"},
        {"field": "destination_location_id", "master": "location_master", "master_key": "location_id"},
    ],
    "outbound_shipment_history": [
        {"field": "product_id", "master": "product_master", "master_key": "product_id"},
        {"field": "origin_location_id", "master": "location_master", "master_key": "location_id"},
        {"field": "destination_location_id", "master": "location_master", "master_key": "location_id"},
    ],
    "production_history": [
        {"field": "product_id", "master": "product_master", "master_key": "product_id"},
        {"field": "location_id", "master": "location_master", "master_key": "location_id"},
    ],
    "inventory_history": [
        {"field": "product_id", "master": "product_master", "master_key": "product_id"},
        {"field": "location_id", "master": "location_master", "master_key": "location_id"},
    ],
    "shipment_cost": [
        # shipment_id references shipment_history, not a pure master — handled via
        # the shipment dataset's own cascade result rather than a master key set.
    ],
}


def build_excluded_key_lookup(master_gold_frames: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, set]]:
    """
    Build a lookup of excluded master keys after scope filtering has been applied
    to master datasets. Returns:
      { master_dataset: { master_key_field: set_of_excluded_key_values } }

    Only includes datasets/fields that are actually present with scope_included column.
    """
    lookup: Dict[str, Dict[str, set]] = {}
    key_field_by_master = {
        "product_master": "product_id",
        "customer_master": "customer_id",
        "location_master": "location_id",
        "vendor_master": "vendor_id",
    }
    for master_name, key_field in key_field_by_master.items():
        df = master_gold_frames.get(master_name)
        if df is None or df.empty or "scope_included" not in df.columns or key_field not in df.columns:
            continue
        excluded_keys = set(str(k) for k in df.loc[~df["scope_included"], key_field].dropna())
        if excluded_keys:
            lookup[master_name] = {key_field: excluded_keys}
    return lookup


def apply_cascade_exclusions(
    df: pd.DataFrame,
    dataset: str,
    excluded_key_lookup: Dict[str, Dict[str, set]],
) -> pd.DataFrame:
    """
    Given a transactional Gold DataFrame that already has scope_included /
    scope_exclusion_reason from its own direct rules, additionally cascade-exclude
    any row whose foreign key references an excluded master record.

    Rows already excluded by direct rules keep their original (more specific) reason.
    Rows newly excluded via cascade get a reason like:
      "Excluded via cascade: product_id 'A' is excluded in product_master"
    """
    df = df.copy()
    if "scope_included" not in df.columns:
        df["scope_included"] = True
        df["scope_exclusion_reason"] = None

    fk_rules = CASCADE_FK_MAP.get(dataset, [])
    if not fk_rules or not excluded_key_lookup:
        return df

    for rule in fk_rules:
        field = rule["field"]
        master = rule["master"]
        master_key = rule["master_key"]
        if field not in df.columns:
            continue
        master_excluded = excluded_key_lookup.get(master, {}).get(master_key)
        if not master_excluded:
            continue

        row_keys = df[field].astype(str)
        cascade_mask = row_keys.isin(master_excluded)
        # Only apply cascade to rows that are still marked in-scope (don't overwrite a
        # more specific direct-rule exclusion reason that already applies to this row).
        newly_excluded = cascade_mask & df["scope_included"]
        if newly_excluded.any():
            reason_series = (
                f"Excluded via cascade: {field} '"
                + row_keys[newly_excluded]
                + f"' is excluded in {master}"
            )
            df.loc[newly_excluded, "scope_exclusion_reason"] = reason_series
            df.loc[newly_excluded, "scope_included"] = False

    return df


def scope_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Summarize scope inclusion for a Gold DataFrame."""
    if "scope_included" not in df.columns or df.empty:
        return {"total": len(df), "included": len(df), "excluded": 0, "pct_excluded": 0.0, "reasons": {}}
    total = len(df)
    included = int(df["scope_included"].sum())
    excluded = total - included
    reasons: Dict[str, int] = {}
    if excluded > 0:
        reason_counts = df.loc[~df["scope_included"], "scope_exclusion_reason"].value_counts()
        reasons = {str(k): int(v) for k, v in reason_counts.items()}
    return {
        "total": total,
        "included": included,
        "excluded": excluded,
        "pct_excluded": round(excluded / total * 100, 1) if total else 0.0,
        "reasons": reasons,
    }
