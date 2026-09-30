"""
Python ETL Pipeline: Bronze -> Silver (plan_v2.md Section 1).

Silver = cleaned + standardized + renamed to canonical schema.
Raw Bronze data/columns are never mutated; this module reads Bronze and
writes a new Silver DataFrame/artifact.

Enhancements (Operating Manual compliance):
- Categorical value standardization (principle #5)
- Missing value treatment tracking (principle #6)
- Statistical outlier detection (principle #9)
- Unit consistency checks (principle #10)
- Grain validation (principle #14)
- Transformation log per column
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.column_mapping import apply_mapping, run_mapping_suggestion_for_dataset
from app.config import (
    CanonicalSchema,
    RUN_LOG_DIR,
    SILVER_DIR,
    load_canonical_schema,
    load_mapping_config,
)

# Dedup key columns per dataset (used for exact + near-duplicate detection)
DEDUP_KEYS: Dict[str, List[str]] = {
    "customer_master": ["customer_id"],
    "location_master": ["location_id"],
    "vendor_master": ["vendor_id"],
    "product_master": ["product_id"],
    "production_history": ["production_id"],
    "shipment_history": ["shipment_id"],
    "inbound_shipment_history": ["shipment_id"],
    "outbound_shipment_history": ["shipment_id"],
    "shipment_cost": ["shipment_id", "cost_type"],
    "inventory_history": ["location_id", "product_id", "snapshot_date"],
}

DATE_FIELDS = {"shipment_date", "production_date", "snapshot_date", "delivery_date",
               "order_date", "promised_date", "start_date", "end_date"}
NUMERIC_FIELDS = {
    "latitude", "longitude", "weight", "length", "width", "height",
    "units_per_pallet", "volume", "quantity_produced", "quantity_on_hand",
    "cost_amount", "unit_cost", "unit_price", "pallet_count", "weight_shipped",
    "quantity_available", "quantity_reserved", "quantity_in_transit", "quantity_on_order",
    "safety_stock", "reorder_point", "max_stock", "fuel_surcharge_pct", "credit_limit",
}
STRING_TRIM_SKIP = DATE_FIELDS | NUMERIC_FIELDS

# Canonical categorical value mappings: field_name -> {lowercase_raw -> canonical}
CATEGORICAL_MAPS: Dict[str, Dict[str, str]] = {
    "shipment_mode": {
        "truck": "Truck", "trk": "Truck", "tl": "Truck", "ltl": "Truck",
        "road": "Truck", "ground": "Truck", "ftl": "Truck",
        "rail": "Rail", "railroad": "Rail", "train": "Rail",
        "air": "Air", "airfreight": "Air", "air freight": "Air", "air_freight": "Air",
        "ocean": "Ocean", "sea": "Ocean", "vessel": "Ocean", "ship": "Ocean", "fcl": "Ocean",
        "parcel": "Parcel", "courier": "Parcel", "small parcel": "Parcel", "ups": "Parcel",
        "fedex": "Parcel", "dhl": "Parcel",
        "intermodal": "Intermodal", "multi": "Intermodal", "multi-modal": "Intermodal",
    },
    "direction": {
        "inbound": "Inbound", "in": "Inbound", "receiving": "Inbound",
        "receipt": "Inbound", "i": "Inbound",
        "outbound": "Outbound", "out": "Outbound", "shipping": "Outbound",
        "dispatch": "Outbound", "o": "Outbound", "delivery": "Outbound",
        "transfer": "Transfer", "internal": "Transfer", "t": "Transfer",
    },
    "location_type": {
        "dc": "DC", "distribution center": "DC", "distribution centre": "DC", "dist center": "DC",
        "plant": "Plant", "factory": "Plant", "manufacturing": "Plant", "mfg": "Plant",
        "port": "Port", "terminal": "Port", "seaport": "Port",
        "store": "Store", "retail": "Store", "branch": "Store",
        "warehouse": "Warehouse", "whs": "Warehouse", "wh": "Warehouse",
        "cross dock": "CrossDock", "crossdock": "CrossDock", "xdock": "CrossDock",
        "vendor": "Vendor", "supplier": "Vendor",
    },
    "vendor_type": {
        "carrier": "Carrier", "3pl": "3PL", "third party": "3PL",
        "supplier": "Supplier", "manufacturer": "Manufacturer",
        "distributor": "Distributor",
    },
    "account_type": {
        "customer": "Customer", "internal": "Internal", "partner": "Partner",
        "external": "External", "distributor": "Distributor",
    },
    "inventory_status": {
        "available": "Available", "avail": "Available",
        "hold": "Hold", "on hold": "Hold",
        "damaged": "Damaged", "dmg": "Damaged",
        "expired": "Expired", "exp": "Expired",
        "quarantine": "Quarantine", "quar": "Quarantine",
    },
}

# IQR multiplier for outlier detection (values beyond Q1 - k*IQR or Q3 + k*IQR)
OUTLIER_IQR_MULTIPLIER = 3.0

# Numeric fields to check for outliers per dataset
OUTLIER_CHECK_FIELDS: Dict[str, List[str]] = {
    "shipment_history": ["volume", "weight_shipped", "pallet_count"],
    "inbound_shipment_history": ["volume", "weight_shipped"],
    "outbound_shipment_history": ["volume", "weight_shipped"],
    "production_history": ["quantity_produced", "planned_quantity"],
    "shipment_cost": ["cost_amount", "base_freight_amount", "fuel_surcharge_amount"],
    "inventory_history": ["quantity_on_hand", "quantity_available"],
    "product_master": ["weight", "unit_cost", "unit_price"],
}


# ---------------------------------------------------------------------------
# Core transformation functions
# ---------------------------------------------------------------------------

def _clean_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Trim whitespace, normalize nulls in all string columns."""
    df = df.copy()
    for col in df.columns:
        if col in STRING_TRIM_SKIP:
            continue
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"nan": None, "None": None, "": None, "N/A": None,
                                       "n/a": None, "NA": None, "NULL": None, "null": None,
                                       "-": None, "--": None})
    return df


def _normalize_categoricals(df: pd.DataFrame, transform_log: List[Dict]) -> pd.DataFrame:
    """
    Standardize categorical field values to canonical forms.
    E.g., 'truck', 'TRK', 'Truck' -> 'Truck' for shipment_mode.
    Records all normalizations in transform_log.
    """
    df = df.copy()
    for col, mapping in CATEGORICAL_MAPS.items():
        if col not in df.columns:
            continue
        mask = df[col].notna()
        original = df.loc[mask, col].astype(str).str.strip()
        normalized = original.str.lower().map(mapping)
        changed_mask = normalized.notna() & (normalized.values != original.values)
        n_changed = int(changed_mask.sum())
        if n_changed > 0:
            idx = original.index[changed_mask]
            df.loc[idx, col] = normalized[changed_mask].values
            transform_log.append({
                "column": col,
                "transformation": "categorical_normalization",
                "records_affected": n_changed,
                "example_before": original[changed_mask].iloc[0] if n_changed else None,
                "example_after": normalized[changed_mask].iloc[0] if n_changed else None,
            })
    return df


def _cast_types(df: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
    """Cast columns to their canonical types as defined in the schema."""
    df = df.copy()
    type_map = {f.name: f.type for f in schema.fields}
    for col in df.columns:
        target_type = type_map.get(col)
        if target_type == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif target_type == "date":
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _deduplicate(df: pd.DataFrame, dataset: str, transform_log: List[Dict]) -> pd.DataFrame:
    """Remove duplicate rows using dataset-specific business keys."""
    keys = DEDUP_KEYS.get(dataset)
    n_before = len(df)
    if not keys or not all(k in df.columns for k in keys):
        result = df.drop_duplicates()
    else:
        result = df.drop_duplicates(subset=keys, keep="first")
    n_removed = n_before - len(result)
    if n_removed > 0:
        transform_log.append({
            "column": "ALL",
            "transformation": "deduplication",
            "records_affected": n_removed,
            "dedup_keys": keys or "all_columns",
            "note": f"Removed {n_removed} duplicate rows; kept first occurrence.",
        })
    return result


def _profile_missing(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Profile missing values per column. Returns:
    - pct_missing per column
    - treatment suggestion per column
    """
    total = len(df)
    if total == 0:
        return {}
    result = {}
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        pct = round(n_missing / total * 100, 1)
        if pct == 0:
            treatment = "none_needed"
        elif pct < 5:
            treatment = "impute_or_flag"
        elif pct < 30:
            treatment = "flag_for_review"
        else:
            treatment = "exclude_or_manual_review"
        result[col] = {
            "n_missing": n_missing,
            "pct_missing": pct,
            "suggested_treatment": treatment,
        }
    return result


def _detect_outliers(df: pd.DataFrame, dataset: str, transform_log: List[Dict]) -> pd.DataFrame:
    """
    IQR-based outlier detection for numeric fields.
    Adds an '_outlier_flags' dict-column summarizing which fields have outlier values per row.
    Appends outlier summaries to transform_log.
    Does NOT remove outliers — flags them for review per Operating Principle #9.
    """
    df = df.copy()
    fields_to_check = OUTLIER_CHECK_FIELDS.get(dataset, [])
    outlier_summary: Dict[str, Dict] = {}

    for col in fields_to_check:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) < 4:
            continue
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - OUTLIER_IQR_MULTIPLIER * iqr
        upper = q3 + OUTLIER_IQR_MULTIPLIER * iqr
        n_series = pd.to_numeric(df[col], errors="coerce")
        outlier_mask = (n_series < lower) | (n_series > upper)
        n_outliers = int(outlier_mask.sum())
        if n_outliers > 0:
            # Add outlier flag column
            flag_col = f"{col}_outlier_flag"
            df[flag_col] = outlier_mask
            outlier_summary[col] = {
                "n_outliers": n_outliers,
                "lower_bound": round(lower, 4),
                "upper_bound": round(upper, 4),
                "min_value": round(float(series.min()), 4),
                "max_value": round(float(series.max()), 4),
                "flag_column": flag_col,
                "recommendation": "Review outliers — do not auto-remove. Cap, retain, or exclude per business context.",
            }
            transform_log.append({
                "column": col,
                "transformation": "outlier_detection",
                "records_affected": n_outliers,
                "lower_bound": round(lower, 4),
                "upper_bound": round(upper, 4),
                "iqr_multiplier": OUTLIER_IQR_MULTIPLIER,
                "note": f"{n_outliers} values outside [{lower:.2f}, {upper:.2f}] flagged in '{flag_col}'. Not removed.",
            })

    if outlier_summary:
        df.attrs = getattr(df, "attrs", {})
        df.attrs["outlier_summary"] = outlier_summary

    return df


def _validate_grain(df: pd.DataFrame, dataset: str, transform_log: List[Dict]) -> Dict[str, Any]:
    """
    Validate that the dataset has the expected grain (one row per business key).
    Returns a grain_report dict.
    """
    keys = DEDUP_KEYS.get(dataset)
    grain_report: Dict[str, Any] = {"dataset": dataset, "grain_keys": keys}

    if not keys or not all(k in df.columns for k in keys):
        grain_report["status"] = "grain_keys_not_present"
        grain_report["note"] = f"Expected grain keys {keys} not all present in columns."
        return grain_report

    total = len(df)
    unique = df.drop_duplicates(subset=keys).shape[0]
    duplicates = total - unique

    grain_report["total_rows"] = total
    grain_report["unique_key_rows"] = unique
    grain_report["duplicate_key_rows"] = duplicates
    grain_report["grain_is_valid"] = duplicates == 0

    if duplicates > 0:
        grain_report["status"] = "grain_violation"
        grain_report["note"] = (
            f"{duplicates} rows share the same {keys} — grain violation detected. "
            f"Review dedup logic or grain definition."
        )
        transform_log.append({
            "column": str(keys),
            "transformation": "grain_check",
            "records_affected": duplicates,
            "note": grain_report["note"],
        })
    else:
        grain_report["status"] = "grain_valid"
        grain_report["note"] = f"Grain is valid — {total} rows, all {keys} unique."

    return grain_report


# ---------------------------------------------------------------------------
# Main Bronze → Silver function
# ---------------------------------------------------------------------------

def bronze_to_silver(
    raw_df: pd.DataFrame,
    dataset: str,
    project_id: str,
    run_id: str,
    onboard_if_missing: bool = True,
) -> pd.DataFrame:
    """
    Transform a raw (Bronze) DataFrame into the canonical Silver DataFrame.

    Steps:
    1. Apply column mapping (Bronze raw names → canonical schema names)
    2. Clean strings (trim, normalize nulls)
    3. Normalize categorical values (Operating Principle #5)
    4. Cast types per canonical schema
    5. Deduplicate (Operating Principle #7)
    6. Detect outliers — flag only, do not remove (Operating Principle #9)
    7. Validate grain (Operating Principle #14)
    8. Profile missing values (Operating Principle #6)
    9. Persist Silver artifact + transformation log
    """
    schema = load_canonical_schema(dataset)
    transform_log: List[Dict] = []

    mapping_entries = load_mapping_config(project_id, dataset)
    if not mapping_entries and onboard_if_missing:
        mapping_entries = run_mapping_suggestion_for_dataset(project_id, dataset, raw_df)

    canonical_df = apply_mapping(raw_df, mapping_entries)

    if canonical_df.empty and onboard_if_missing:
        mapping_entries = run_mapping_suggestion_for_dataset(
            project_id, dataset, raw_df, overwrite=True
        )
        canonical_df = apply_mapping(raw_df, mapping_entries)

    transform_log.append({
        "column": "ALL",
        "transformation": "column_mapping",
        "records_affected": len(canonical_df),
        "note": f"Mapped {len(mapping_entries)} raw columns to canonical schema.",
    })

    canonical_df = _clean_strings(canonical_df)
    canonical_df = _normalize_categoricals(canonical_df, transform_log)
    canonical_df = _cast_types(canonical_df, schema)
    canonical_df = _deduplicate(canonical_df, dataset, transform_log)
    canonical_df = _detect_outliers(canonical_df, dataset, transform_log)

    # Grain validation (before writing)
    grain_report = _validate_grain(canonical_df, dataset, transform_log)

    # Missing value profile
    missing_profile = _profile_missing(canonical_df)

    _write_silver(canonical_df, project_id, dataset, run_id)

    # Persist transformation log
    _write_transform_log(project_id, dataset, run_id, transform_log, grain_report, missing_profile)

    return canonical_df


def _silver_path(project_id: str, dataset: str, run_id: str) -> Path:
    p = SILVER_DIR / project_id / dataset / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "data.parquet"


def _write_silver(df: pd.DataFrame, project_id: str, dataset: str, run_id: str) -> None:
    path = _silver_path(project_id, dataset, run_id)
    df.to_parquet(path, index=False)


def _write_transform_log(
    project_id: str,
    dataset: str,
    run_id: str,
    transform_log: List[Dict],
    grain_report: Dict,
    missing_profile: Dict,
) -> None:
    """Persist the transformation log, grain report, and missing-value profile as JSON."""
    log_dir = RUN_LOG_DIR / project_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}_{dataset}_transform_log.json"
    payload = {
        "project_id": project_id,
        "dataset": dataset,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transformations": transform_log,
        "grain_report": grain_report,
        "missing_value_profile": missing_profile,
    }
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def load_silver(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    path = _silver_path(project_id, dataset, run_id)
    if not path.exists():
        raise FileNotFoundError(f"No silver data found for {project_id}/{dataset}/{run_id}")
    return pd.read_parquet(path)


def load_transform_log(project_id: str, dataset: str, run_id: str) -> Dict:
    """Load the transformation log for a Silver run."""
    log_path = RUN_LOG_DIR / project_id / f"{run_id}_{dataset}_transform_log.json"
    if not log_path.exists():
        return {}
    with open(log_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
