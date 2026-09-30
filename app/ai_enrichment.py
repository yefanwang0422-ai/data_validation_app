"""
AI Enrichment Engine (plan_v2.md Section 6).

Fills missing geo fields using three evidence layers (in priority order):

1. Address parsing — if address_line_1 contains a full address, parse
   city/state/postal_code from it using regex patterns.

2. Cross-record evidence — infer from other records sharing the same
   postal code in this dataset (deterministic, high confidence).

3. Geocoding — if lat/lon are missing but city+state or postal_code are
   present, use geopy/Nominatim (free, no API key) to geocode.
   Falls back gracefully to hardcoded table if network is unavailable.

Every filled value is:
- Never written into raw/Silver columns (Gold-layer only)
- Flagged in the manual review queue
- Confidence-gated (only applied if confidence >= threshold)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

CONFIDENCE_THRESHOLD = 0.6
ENRICHABLE_FIELDS = ["city", "state", "postal_code", "latitude", "longitude"]

# Common US address patterns for city/state/zip parsing
_CITY_STATE_ZIP_RE = re.compile(
    r'(?:^|,\s*)([A-Za-z\s]+?)\s*,\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)\s*$',
    re.IGNORECASE,
)
_CITY_STATE_RE = re.compile(
    r'(?:^|,\s*)([A-Za-z\s]+?)\s*,\s*([A-Z]{2})\s*$',
    re.IGNORECASE,
)

# Fallback lookup table for major US cities (used when geocoding is unavailable)
_CITY_STATE_TO_LATLON: Dict[str, tuple] = {
    ("chicago", "il"): (41.8827, -87.6233),
    ("dallas", "tx"): (32.7767, -96.7970),
    ("houston", "tx"): (29.7604, -95.3698),
    ("atlanta", "ga"): (33.7490, -84.3880),
    ("columbus", "oh"): (39.9612, -82.9988),
    ("memphis", "tn"): (35.1495, -90.0490),
    ("denver", "co"): (39.7392, -104.9903),
    ("phoenix", "az"): (33.4484, -112.0740),
    ("newark", "nj"): (40.7357, -74.1724),
    ("sacramento", "ca"): (38.5816, -121.4944),
    ("charlotte", "nc"): (35.2271, -80.8431),
    ("los angeles", "ca"): (34.0522, -118.2437),
    ("new york", "ny"): (40.7128, -74.0060),
    ("seattle", "wa"): (47.6062, -122.3321),
    ("miami", "fl"): (25.7617, -80.1918),
    ("boston", "ma"): (42.3601, -71.0589),
    ("minneapolis", "mn"): (44.9778, -93.2650),
    ("portland", "or"): (45.5051, -122.6750),
    ("san francisco", "ca"): (37.7749, -122.4194),
    ("las vegas", "nv"): (36.1699, -115.1398),
    ("detroit", "mi"): (42.3314, -83.0458),
    ("baltimore", "md"): (39.2904, -76.6122),
    ("louisville", "ky"): (38.2527, -85.7585),
    ("jacksonville", "fl"): (30.3322, -81.6557),
    ("indianapolis", "in"): (39.7684, -86.1581),
    ("nashville", "tn"): (36.1627, -86.7816),
    ("san antonio", "tx"): (29.4241, -98.4936),
    ("austin", "tx"): (30.2672, -97.7431),
    ("fort worth", "tx"): (32.7555, -97.3308),
    ("el paso", "tx"): (31.7619, -106.4850),
    ("albuquerque", "nm"): (35.0844, -106.6504),
    ("tucson", "az"): (32.2226, -110.9747),
    ("fresno", "ca"): (36.7378, -119.7871),
    ("mesa", "az"): (33.4152, -111.8315),
    ("kansas city", "mo"): (39.0997, -94.5786),
    ("omaha", "ne"): (41.2565, -95.9345),
    ("cleveland", "oh"): (41.4993, -81.6944),
    ("raleigh", "nc"): (35.7796, -78.6382),
    ("virginia beach", "va"): (36.8529, -75.9780),
}


@dataclass
class EnrichmentResult:
    record_id: Any
    field: str
    candidate_value: Any
    confidence: float
    rationale: str
    applied: bool
    manual_review_required: bool = True


# ---------------------------------------------------------------------------
# Evidence layer 1: address parsing
# ---------------------------------------------------------------------------

def _parse_address(address: str) -> Dict[str, Optional[str]]:
    """Parse city/state/postal_code from an address string."""
    if not address or not isinstance(address, str):
        return {}
    addr = address.strip()
    m = _CITY_STATE_ZIP_RE.search(addr)
    if m:
        return {"city": m.group(1).strip(), "state": m.group(2).upper(), "postal_code": m.group(3)}
    m = _CITY_STATE_RE.search(addr)
    if m:
        return {"city": m.group(1).strip(), "state": m.group(2).upper(), "postal_code": None}
    return {}


# ---------------------------------------------------------------------------
# Evidence layer 2: cross-record postal code lookup
# ---------------------------------------------------------------------------

def _infer_from_postal_lookup(postal_code: str, reference_table: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Look up city/state/lat/lon from other master records sharing the same postal code."""
    if not postal_code or reference_table is None or reference_table.empty:
        return None
    if "postal_code" not in reference_table.columns:
        return None
    match = reference_table[reference_table["postal_code"] == postal_code]
    dropna_cols = [c for c in ["city", "state"] if c in match.columns]
    if dropna_cols:
        match = match.dropna(subset=dropna_cols, how="all")
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "city": row.get("city"),
        "state": row.get("state"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
    }


# ---------------------------------------------------------------------------
# Evidence layer 3: geocoding
# ---------------------------------------------------------------------------

def _geocode(city: Optional[str], state: Optional[str], postal_code: Optional[str]) -> Optional[tuple]:
    """
    Return (latitude, longitude) for the given location.
    Tries hardcoded table first (fast, no network), then geopy/Nominatim.
    """
    # 1. Hardcoded lookup
    if city and state:
        key = (city.strip().lower(), state.strip().lower())
        if key in _CITY_STATE_TO_LATLON:
            return _CITY_STATE_TO_LATLON[key]

    # 2. geopy/Nominatim (requires network, graceful fallback)
    try:
        from geopy.geocoders import Nominatim

        geocoder = Nominatim(user_agent="network_design_data_prep_v1", timeout=5)
        query_parts = []
        if city:
            query_parts.append(city)
        if state:
            query_parts.append(state)
        if postal_code:
            query_parts.append(postal_code)
        query_parts.append("USA")
        if len(query_parts) < 2:
            return None
        location = geocoder.geocode(", ".join(query_parts))
        if location:
            return (round(location.latitude, 6), round(location.longitude, 6))
    except Exception:  # noqa: BLE001
        pass

    return None


# ---------------------------------------------------------------------------
# Helper: apply value and log review item
# ---------------------------------------------------------------------------

def _apply_and_log(
    gold: pd.DataFrame,
    idx: Any,
    field_name: str,
    candidate: Any,
    confidence: float,
    rationale: str,
    record_id: Any,
    dataset: str,
    run_id: str,
    now: str,
    review_items: List[Dict[str, Any]],
) -> None:
    """Apply candidate value to Gold (if above threshold) and log a review item."""
    applied = confidence >= CONFIDENCE_THRESHOLD
    if applied:
        gold.at[idx, field_name] = candidate
        if "needs_review" in gold.columns:
            gold.at[idx, "needs_review"] = True
            gold.at[idx, "row_status"] = "needs_review"

    review_items.append(
        EnrichmentResult(
            record_id=record_id,
            field=field_name,
            candidate_value=candidate,
            confidence=confidence,
            rationale=rationale,
            applied=applied,
            manual_review_required=True,
        ).__dict__
        | {
            "dataset_name": dataset,
            "run_id": run_id,
            "created_at": now,
        }
    )


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------

def enrich_missing_geo_fields(
    gold_df: pd.DataFrame,
    dataset: str,
    run_id: str,
) -> "tuple[pd.DataFrame, List[Dict[str, Any]]]":
    """
    Attempt AI-assisted fill for missing city/state/postal_code/latitude/longitude.

    Evidence priority per record:
    1. Address parsing from address_line_1
    2. Cross-record postal code evidence (same postal code in this dataset)
    3. Geocoding (hardcoded city table + geopy/Nominatim fallback)
    """
    gold = gold_df.copy()
    review_items: List[Dict[str, Any]] = []

    available_fields = [f for f in ENRICHABLE_FIELDS if f in gold.columns]
    if not available_fields:
        return gold, review_items

    # Build reference table from geo columns that exist
    geo_cols = ["postal_code", "city", "state", "latitude", "longitude"]
    available_geo = [c for c in geo_cols if c in gold.columns]
    reference_table = (
        gold[available_geo].copy()
        if "postal_code" in gold.columns and len(available_geo) > 1
        else None
    )

    id_col_candidates = [c for c in gold.columns if c.endswith("_id")]
    id_col = id_col_candidates[0] if id_col_candidates else None
    now = datetime.now(timezone.utc).isoformat()

    for idx in gold.index:
        row = gold.loc[idx]
        record_id = gold.at[idx, id_col] if id_col else idx

        # ---- Layer 1: address parsing ----
        address_raw = row.get("address_line_1") if "address_line_1" in gold.columns else None
        address_str = str(address_raw) if address_raw is not None else ""
        parsed = _parse_address(address_str) if address_str not in ("", "nan", "None") else {}

        # ---- Layer 2: cross-record evidence ----
        postal_from_parse = parsed.get("postal_code")
        postal_in_row = str(row.get("postal_code", "")).strip()
        effective_postal = postal_from_parse or (postal_in_row if postal_in_row not in ("", "nan", "None") else None)
        cross_ref = _infer_from_postal_lookup(effective_postal, reference_table) if effective_postal else None

        # ---- Enrich city ----
        if "city" in gold.columns:
            val = str(gold.at[idx, "city"]).strip() if not pd.isna(gold.at[idx, "city"]) else ""
            if val in ("", "nan", "None"):
                if parsed.get("city"):
                    _apply_and_log(gold, idx, "city", parsed["city"], 0.75,
                                   f"Parsed city from address_line_1.",
                                   record_id, dataset, run_id, now, review_items)
                elif cross_ref and cross_ref.get("city"):
                    _apply_and_log(gold, idx, "city", cross_ref["city"], 0.9,
                                   f"Inferred city from record sharing postal code '{effective_postal}'.",
                                   record_id, dataset, run_id, now, review_items)

        # ---- Enrich state ----
        if "state" in gold.columns:
            val = str(gold.at[idx, "state"]).strip() if not pd.isna(gold.at[idx, "state"]) else ""
            if val in ("", "nan", "None"):
                if parsed.get("state"):
                    _apply_and_log(gold, idx, "state", parsed["state"], 0.75,
                                   f"Parsed state from address_line_1.",
                                   record_id, dataset, run_id, now, review_items)
                elif cross_ref and cross_ref.get("state"):
                    _apply_and_log(gold, idx, "state", cross_ref["state"], 0.9,
                                   f"Inferred state from record sharing postal code '{effective_postal}'.",
                                   record_id, dataset, run_id, now, review_items)

        # ---- Enrich postal_code ----
        if "postal_code" in gold.columns:
            val = str(gold.at[idx, "postal_code"]).strip() if not pd.isna(gold.at[idx, "postal_code"]) else ""
            if val in ("", "nan", "None") and parsed.get("postal_code"):
                _apply_and_log(gold, idx, "postal_code", parsed["postal_code"], 0.75,
                               f"Parsed postal code from address_line_1.",
                               record_id, dataset, run_id, now, review_items)

        # ---- Enrich lat/lon ----
        lat_col_exists = "latitude" in gold.columns
        lon_col_exists = "longitude" in gold.columns
        if not lat_col_exists and not lon_col_exists:
            continue

        lat_val = gold.at[idx, "latitude"] if lat_col_exists else None
        lon_val = gold.at[idx, "longitude"] if lon_col_exists else None
        lat_missing = lat_col_exists and (pd.isna(lat_val) or str(lat_val).strip() in ("", "nan", "None"))
        lon_missing = lon_col_exists and (pd.isna(lon_val) or str(lon_val).strip() in ("", "nan", "None"))

        if not (lat_missing or lon_missing):
            continue

        # Try cross-ref first (no network required)
        if cross_ref and cross_ref.get("latitude") and cross_ref.get("longitude"):
            if lat_missing and lat_col_exists:
                _apply_and_log(gold, idx, "latitude", cross_ref["latitude"], 0.9,
                               f"Inferred latitude from record sharing postal code '{effective_postal}'.",
                               record_id, dataset, run_id, now, review_items)
            if lon_missing and lon_col_exists:
                _apply_and_log(gold, idx, "longitude", cross_ref["longitude"], 0.9,
                               f"Inferred longitude from record sharing postal code '{effective_postal}'.",
                               record_id, dataset, run_id, now, review_items)
        else:
            # Geocode from city+state+postal
            city_for_geo = str(gold.at[idx, "city"]).strip() if lat_col_exists and "city" in gold.columns and not pd.isna(gold.at[idx, "city"]) else None
            state_for_geo = str(gold.at[idx, "state"]).strip() if "state" in gold.columns and not pd.isna(gold.at[idx, "state"]) else None
            postal_for_geo = effective_postal

            if city_for_geo in ("", "nan", "None"):
                city_for_geo = None
            if state_for_geo in ("", "nan", "None"):
                state_for_geo = None

            if city_for_geo or postal_for_geo:
                coords = _geocode(city_for_geo, state_for_geo, postal_for_geo)
                if coords:
                    lat_geocoded, lon_geocoded = coords
                    source = "city/state hardcoded table" if (city_for_geo and state_for_geo and (city_for_geo.lower(), state_for_geo.lower()) in _CITY_STATE_TO_LATLON) else "geopy/Nominatim geocoding"
                    if lat_missing and lat_col_exists:
                        _apply_and_log(gold, idx, "latitude", lat_geocoded, 0.7,
                                       f"Geocoded latitude from {source} for '{city_for_geo}, {state_for_geo} {postal_for_geo}'.",
                                       record_id, dataset, run_id, now, review_items)
                    if lon_missing and lon_col_exists:
                        _apply_and_log(gold, idx, "longitude", lon_geocoded, 0.7,
                                       f"Geocoded longitude from {source} for '{city_for_geo}, {state_for_geo} {postal_for_geo}'.",
                                       record_id, dataset, run_id, now, review_items)

    return gold, review_items
