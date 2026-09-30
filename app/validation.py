"""
Validation & Cross-Reference Engine (plan_v2.md Sections 3 & 5).

Operates on canonical Silver DataFrames and produces Gold DataFrames with:
- validated_* columns / flags
- row-level status: "valid" | "invalid" | "needs_review"
- an issue log (list of dict records) for every failed check

Raw/Silver values are never overwritten -- validation results are appended
as new columns (`is_valid`, `validation_issues`, per-field flags).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import CanonicalSchema, load_canonical_schema


@dataclass
class IssueRecord:
    dataset_name: str
    run_id: str
    record_id: Any
    canonical_field: str
    issue_type: str
    issue_description: str
    severity: str
    raw_value: Any = None
    validated_value: Any = None
    confidence_score: Optional[float] = None
    manual_review_required: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


# ---------------------------------------------------------------------------
# Mandatory field / range / format checks
# ---------------------------------------------------------------------------

NUMERIC_NONNEGATIVE_FIELDS = {
    "weight",
    "length",
    "width",
    "height",
    "units_per_pallet",
    "volume",
    "quantity_produced",
    "cost_amount",
}
# quantity_on_hand allowed to be zero but negative is an exception (handled separately)

LAT_RANGE = (-90.0, 90.0)
LON_RANGE = (-180.0, 180.0)


def _record_id_col(dataset: str) -> Optional[str]:
    id_cols = {
        "customer_master": "customer_id",
        "location_master": "location_id",
        "vendor_master": "vendor_id",
        "product_master": "product_id",
        "production_history": "production_id",
        "shipment_history": "shipment_id",
        "shipment_cost": "shipment_id",
        "inventory_history": "location_id",
    }
    return id_cols.get(dataset)


def validate_dataset(
    df: pd.DataFrame, dataset: str, run_id: str
) -> "tuple[pd.DataFrame, List[Dict[str, Any]]]":
    """
    Apply mandatory/range/format checks to a canonical Silver DataFrame.

    Returns (gold_df_with_flags, issue_log_entries)
    """
    schema = load_canonical_schema(dataset)
    gold = df.copy()
    issues: List[Dict[str, Any]] = []
    id_col = _record_id_col(dataset)

    row_flags = pd.Series([True] * len(gold), index=gold.index)  # True = valid so far
    needs_review = pd.Series([False] * len(gold), index=gold.index)

    def record_issue(idx, field_name, issue_type, description, severity, raw_val=None, review=False):
        rid = gold.at[idx, id_col] if id_col and id_col in gold.columns else idx
        issues.append(
            IssueRecord(
                dataset_name=dataset,
                run_id=run_id,
                record_id=rid,
                canonical_field=field_name,
                issue_type=issue_type,
                issue_description=description,
                severity=severity,
                raw_value=raw_val,
                manual_review_required=review,
            ).to_dict()
        )

    # Mandatory field checks
    for f in schema.required_field_names:
        if f not in gold.columns:
            continue
        missing_mask = gold[f].isna() | (gold[f].astype(str).str.strip() == "")
        for idx in gold.index[missing_mask]:
            record_issue(
                idx, f, "missing_mandatory_field",
                f"Required field '{f}' is missing.", "high",
                raw_val=None, review=(f in ("city", "state", "postal_code", "latitude", "longitude")),
            )
            row_flags[idx] = False
            if f in ("city", "state", "postal_code", "latitude", "longitude"):
                needs_review[idx] = True

    # Numeric non-negative checks
    for f in NUMERIC_NONNEGATIVE_FIELDS:
        if f not in gold.columns:
            continue
        invalid_mask = gold[f].notna() & (gold[f] < 0)
        for idx in gold.index[invalid_mask]:
            record_issue(
                idx, f, "invalid_numeric_value",
                f"Field '{f}' has a negative value ({gold.at[idx, f]}).", "high",
                raw_val=gold.at[idx, f],
            )
            row_flags[idx] = False

    # inventory quantity_on_hand: negative flagged as exception (not necessarily invalid business fact,
    # but flagged per plan_v2.md Section 3)
    if "quantity_on_hand" in gold.columns:
        invalid_mask = gold["quantity_on_hand"].notna() & (gold["quantity_on_hand"] < 0)
        for idx in gold.index[invalid_mask]:
            record_issue(
                idx, "quantity_on_hand", "negative_inventory_exception",
                f"Negative on-hand quantity ({gold.at[idx, 'quantity_on_hand']}).", "medium",
                raw_val=gold.at[idx, "quantity_on_hand"], review=True,
            )
            needs_review[idx] = True

    # Lat/Lon range checks
    if "latitude" in gold.columns:
        bad = gold["latitude"].notna() & ~gold["latitude"].between(*LAT_RANGE)
        for idx in gold.index[bad]:
            record_issue(idx, "latitude", "invalid_range", "Latitude out of range.", "high", gold.at[idx, "latitude"])
            row_flags[idx] = False
    if "longitude" in gold.columns:
        bad = gold["longitude"].notna() & ~gold["longitude"].between(*LON_RANGE)
        for idx in gold.index[bad]:
            record_issue(idx, "longitude", "invalid_range", "Longitude out of range.", "high", gold.at[idx, "longitude"])
            row_flags[idx] = False

    # Direction value check (shipment_history: must be Inbound or Outbound)
    if dataset == "shipment_history" and "direction" in gold.columns:
        valid_directions = {"inbound", "outbound"}
        bad_dir = gold["direction"].notna() & ~gold["direction"].astype(str).str.strip().str.lower().isin(valid_directions)
        for idx in gold.index[bad_dir]:
            record_issue(
                idx, "direction", "invalid_direction_value",
                f"Direction value '{gold.at[idx, 'direction']}' is not valid. Must be 'Inbound' or 'Outbound'.",
                "high",
                raw_val=gold.at[idx, "direction"],
            )
            row_flags[idx] = False

    gold["is_valid"] = row_flags
    gold["needs_review"] = needs_review
    gold["row_status"] = gold.apply(
        lambda r: "needs_review" if r["needs_review"] else ("valid" if r["is_valid"] else "invalid"),
        axis=1,
    )

    return gold, issues


# ---------------------------------------------------------------------------
# Cross-reference engine
# ---------------------------------------------------------------------------

CROSS_REFERENCE_RULES: Dict[str, List[Dict[str, str]]] = {
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
        # destination_location_id uses dual-master lookup — see special handling in cross_reference_check()
        {"field": "destination_location_id", "master": "location_master|customer_master", "master_key": "location_id|customer_id"},
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
        {"field": "shipment_id", "master": "shipment_history", "master_key": "shipment_id"},
    ],
}


def _strip_prefix(value: str) -> str:
    """Strip leading non-numeric prefix characters for fuzzy ID matching.
    e.g. 'PL1928' -> '1928', 'LOC-001' -> '001', 'CUST-0001' -> '0001', '1928' -> '1928'
    """
    import re
    if not value:
        return value
    # Remove leading letters, dashes, underscores, spaces
    stripped = re.sub(r'^[A-Za-z_\-\s]+', '', str(value).strip())
    return stripped if stripped else str(value).strip()


def _build_normalized_key_map(keys: set) -> Dict[str, str]:
    """Return a dict of stripped_key -> original_key for fuzzy prefix matching."""
    result = {}
    for k in keys:
        stripped = _strip_prefix(str(k))
        if stripped and stripped != str(k):  # only add if actually different after stripping
            result[stripped] = str(k)
    return result


def cross_reference_check(
    gold_df: pd.DataFrame,
    dataset: str,
    run_id: str,
    master_frames: Dict[str, pd.DataFrame],
) -> "tuple[pd.DataFrame, List[Dict[str, Any]]]":
    """
    Validate transactional foreign keys against master datasets.

    Features:
    - Prefix-strip fuzzy matching: 'PL1928' matches 'LOC-1928' or '1928' by stripping
      non-numeric prefixes. Matched via prefix-stripping are flagged as soft matches
      (match_type='prefix_stripped') rather than hard exceptions.
    - For shipment_history, origin/destination can also match vendor_master (inbound flow).
    """
    rules = CROSS_REFERENCE_RULES.get(dataset, [])
    gold = gold_df.copy()
    exceptions: List[Dict[str, Any]] = []
    id_col = _record_id_col(dataset)
    now = datetime.now(timezone.utc).isoformat()

    for rule in rules:
        field_name = rule["field"]
        if field_name not in gold.columns:
            continue
        master_name = rule["master"]
        master_key = rule["master_key"]
        # Handle dual-master rules (pipe-separated: "location_master|customer_master")
        is_dual_master = "|" in master_name
        if is_dual_master:
            master_names = master_name.split("|")
            master_keys_list = master_key.split("|")
            dual_keys: Dict[str, set] = {}  # master_name -> valid_keys
            for mn, mk in zip(master_names, master_keys_list):
                mdf = master_frames.get(mn)
                if mdf is not None and mk in mdf.columns:
                    dual_keys[mn] = set(str(k) for k in mdf[mk].dropna())
                else:
                    dual_keys[mn] = set()
            if not any(dual_keys.values()):
                continue  # No reference data at all
            # Combined set for initial validity check
            all_valid_keys = set().union(*dual_keys.values())
            normalized_map = _build_normalized_key_map(all_valid_keys)

            flag_col = f"{field_name}_valid_ref"
            gold[flag_col] = gold[field_name].isna()
            # Initialize destination_type column if not present
            if "destination_type" not in gold.columns:
                gold["destination_type"] = None

            for idx in gold.index[gold[field_name].notna()]:
                raw_val = str(gold.at[idx, field_name]).strip()
                rid = gold.at[idx, id_col] if id_col and id_col in gold.columns else idx
                stripped_val = _strip_prefix(raw_val)

                # Classify destination type
                dest_type = None
                matched_master = None
                for mn, keys in dual_keys.items():
                    n_map = _build_normalized_key_map(keys)
                    if raw_val in keys or stripped_val in keys or stripped_val in n_map:
                        matched_master = mn
                        dest_type = "internal" if mn == "location_master" else "external"
                        break

                if dest_type is not None:
                    gold.at[idx, flag_col] = True
                    gold.at[idx, "destination_type"] = dest_type
                    if raw_val not in all_valid_keys:
                        # Soft prefix match
                        exceptions.append({
                            "dataset_name": dataset, "run_id": run_id, "record_id": rid,
                            "field": field_name, "invalid_value": raw_val,
                            "matched_value": normalized_map.get(stripped_val, stripped_val),
                            "expected_master": matched_master,
                            "match_type": "prefix_stripped", "destination_type": dest_type,
                            "count": 1, "created_at": now,
                        })
                else:
                    gold.at[idx, flag_col] = False
                    gold.at[idx, "destination_type"] = "unknown"
                    exceptions.append({
                        "dataset_name": dataset, "run_id": run_id, "record_id": rid,
                        "field": field_name, "invalid_value": raw_val, "matched_value": None,
                        "expected_master": "|".join(master_names),
                        "match_type": "no_match", "destination_type": "unknown",
                        "count": 1, "created_at": now,
                    })
                    gold.at[idx, "is_valid"] = False
                    gold.at[idx, "row_status"] = "invalid" if gold.at[idx, "row_status"] != "needs_review" else "needs_review"
            continue  # Skip the standard single-master logic below

        master_df = master_frames.get(master_name)

        # If the master table simply isn't available this run, skip rather than
        # flagging every record -- the app works with whatever data exists.
        master_available = master_df is not None and master_key in master_df.columns
        vendor_df = master_frames.get("vendor_master")
        vendor_available = vendor_df is not None and "vendor_id" in vendor_df.columns

        is_shipment_location_field = dataset == "shipment_history" and field_name in (
            "destination_location_id",
            "origin_location_id",
        )
        if not master_available and not (is_shipment_location_field and vendor_available):
            continue  # No reference data available -- skip, don't penalize.

        valid_keys = set(str(k) for k in master_df[master_key].dropna()) if master_available else set()

        # Special-case: shipment origin/destination can also be vendor (inbound flow)
        if is_shipment_location_field and vendor_available:
            valid_keys |= set(str(k) for k in vendor_df["vendor_id"].dropna())

        # Build prefix-stripped lookup for fuzzy matching (e.g., 'PL1928' -> '1928')
        normalized_map = _build_normalized_key_map(valid_keys)

        flag_col = f"{field_name}_valid_ref"
        gold[flag_col] = gold[field_name].isna()  # NA values are not exceptions

        for idx in gold.index[gold[field_name].notna()]:
            raw_val = str(gold.at[idx, field_name]).strip()
            rid = gold.at[idx, id_col] if id_col and id_col in gold.columns else idx

            if raw_val in valid_keys:
                # Exact match — valid
                gold.at[idx, flag_col] = True
            else:
                stripped_val = _strip_prefix(raw_val)
                if stripped_val in valid_keys or stripped_val in normalized_map:
                    # Prefix-stripped match — soft match, still valid but noted
                    gold.at[idx, flag_col] = True
                    matched_original = normalized_map.get(stripped_val, stripped_val)
                    exceptions.append({
                        "dataset_name": dataset,
                        "run_id": run_id,
                        "record_id": rid,
                        "field": field_name,
                        "invalid_value": raw_val,
                        "matched_value": matched_original,
                        "expected_master": master_name,
                        "match_type": "prefix_stripped",
                        "count": 1,
                        "created_at": now,
                    })
                else:
                    # No match at all — hard exception
                    gold.at[idx, flag_col] = False
                    exceptions.append({
                        "dataset_name": dataset,
                        "run_id": run_id,
                        "record_id": rid,
                        "field": field_name,
                        "invalid_value": raw_val,
                        "matched_value": None,
                        "expected_master": master_name,
                        "match_type": "no_match",
                        "count": 1,
                        "created_at": now,
                    })
                    gold.at[idx, "is_valid"] = False
                    gold.at[idx, "row_status"] = "invalid" if gold.at[idx, "row_status"] != "needs_review" else "needs_review"

    return gold, exceptions


def flag_in_scope_products(product_gold: pd.DataFrame, shipment_silver: pd.DataFrame) -> pd.DataFrame:
    """
    Product master enrichment: flag products appearing in outbound Shipment History
    as 'in scope' for network modeling (plan_v2.md Section 3).
    """
    product_gold = product_gold.copy()
    outbound_products = set()
    if "direction" in shipment_silver.columns and "product_id" in shipment_silver.columns:
        outbound_products = set(
            shipment_silver.loc[shipment_silver["direction"] == "Outbound", "product_id"].dropna()
        )
    elif "product_id" in shipment_silver.columns:
        outbound_products = set(shipment_silver["product_id"].dropna())

    product_gold["in_scope"] = product_gold["product_id"].isin(outbound_products)
    return product_gold


def flag_in_scope_products_extended(
    product_gold: pd.DataFrame,
    shipment_frames: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Extended version: flags products appearing in any of:
    - outbound_shipment_history (outbound-only dataset)
    - shipment_history (combined, Outbound direction)
    as in-scope for network modeling.
    """
    product_gold = product_gold.copy()
    outbound_products: set = set()

    for key in ("outbound_shipment_history", "shipment_history"):
        df = shipment_frames.get(key)
        if df is None or "product_id" not in df.columns:
            continue
        if "direction" in df.columns:
            outbound_products |= set(df.loc[df["direction"] == "Outbound", "product_id"].dropna())
        else:
            outbound_products |= set(df["product_id"].dropna())

    product_gold["in_scope"] = product_gold["product_id"].isin(outbound_products)
    return product_gold
