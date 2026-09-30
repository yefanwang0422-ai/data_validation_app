"""
Geographic origin→destination (OD) lane aggregation for Business Insights maps.

Produces JSON-friendly structures consumed by the frontend to render:
- Inbound OD map: vendor/supplier -> facility
- Outbound OD map: facility -> customer

Assumptions:
- Shipment datasets contain origin_location_id and destination_location_id (or raw fallbacks).
- location_master has address + optional latitude/longitude.
- customer_master/vendor_master may have address fields; if not, we will attempt to
  geocode whatever is available (city/state/postal/country).

Design goals:
- Business-friendly, robust to missing datasets/columns.
- Never hard-fail if some fields are missing; instead omit un-geocodable lanes.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd

from app.business_metrics import _add_fallback_cols, _gold
from app.geo import GeoInput, geocode_geo_input


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _first_existing_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _build_geo_input_from_row(row: pd.Series) -> GeoInput:
    def g(name: str) -> str:
        v = row.get(name, "")
        if v is None:
            return ""
        return str(v)
    return GeoInput(
        address_line_1=g("address_line_1"),
        address_line_2=g("address_line_2"),
        city=g("city"),
        state=g("state"),
        postal_code=g("postal_code"),
        country=g("country"),
    )


def _resolve_points(
    project_id: str,
    entities: pd.DataFrame,
    id_col: str,
    name_col: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Build a dict: entity_id -> {id, name, lat, lon, ...}.

    If latitude/longitude are missing, attempt geocoding based on address fields.
    """
    if entities.empty or id_col not in entities.columns:
        return {}

    entities = entities.copy()

    # Normalized output keys
    entities["__id"] = entities[id_col].astype(str)
    if name_col and name_col in entities.columns:
        entities["__name"] = entities[name_col].astype(str)
    else:
        entities["__name"] = entities["__id"]

    lat_col = "latitude" if "latitude" in entities.columns else None
    lon_col = "longitude" if "longitude" in entities.columns else None

    out: Dict[str, Dict[str, Any]] = {}
    for _, r in entities.drop_duplicates("__id").iterrows():
        ent_id = str(r["__id"])
        lat = None
        lon = None

        if lat_col and lon_col:
            try:
                lat = float(r.get(lat_col)) if pd.notna(r.get(lat_col)) else None
                lon = float(r.get(lon_col)) if pd.notna(r.get(lon_col)) else None
            except Exception:
                lat = None
                lon = None

        if lat is None or lon is None:
            gi = _build_geo_input_from_row(r)
            coords = geocode_geo_input(project_id, gi)
            if coords:
                lat, lon = coords

        out[ent_id] = {
            "id": ent_id,
            "name": str(r.get("__name") or ent_id),
            "city": r.get("city"),
            "state": r.get("state"),
            "country": r.get("country"),
            "lat": lat,
            "lon": lon,
        }
    return out


def _aggregate_lanes(
    df: pd.DataFrame,
    origin_col: str,
    dest_col: str,
    value_col: Optional[str] = None,
    top_n: int = 150,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df[origin_col] = df[origin_col].astype(str)
    df[dest_col] = df[dest_col].astype(str)

    if value_col and value_col in df.columns:
        df[value_col] = _num(df[value_col])
        df = df.dropna(subset=[value_col])
        agg = df.groupby([origin_col, dest_col])[value_col].sum().reset_index()
        agg = agg.rename(columns={value_col: "value"})
    else:
        agg = df.groupby([origin_col, dest_col]).size().reset_index(name="value")

    agg = agg.sort_values("value", ascending=False).head(top_n)
    return agg


def build_inbound_od_map(
    project_id: str,
    run_id: str,
    status_filter: str = "all",
    top_n: int = 150,
    metric: Literal["volume", "count"] = "volume",
) -> Dict[str, Any]:
    """
    Inbound = vendor/supplier -> facility.

    Practical mapping in this app:
    - If inbound_shipment_history has origin_location_id, treat that as "supplier site"
      (or upstream location).
    - Destination is destination_location_id (receiving facility).

    If vendor_id exists but vendor_master lacks location info, we still return lanes
    by location_id (most robust across datasets).
    """
    inbound = _gold(project_id, "inbound_shipment_history", run_id, status_filter)
    if inbound.empty:
        # Fallback: try shipment_history filtered by direction if available.
        shipments = _gold(project_id, "shipment_history", run_id, status_filter)
        if not shipments.empty and "direction" in shipments.columns:
            inbound = shipments[shipments["direction"].astype(str).str.strip().str.lower() == "inbound"]
        else:
            inbound = shipments

    if inbound.empty:
        return {"mode": "inbound", "nodes": [], "lanes": [], "note": "No inbound shipment data found."}

    # Prefer explicit canonical "volume" if present; otherwise use common shipment quantity
    # fields seen in the demo data (e.g., weight_shipped or raw__Quantity).
    inbound = _add_fallback_cols(inbound, "origin_location_id", "destination_location_id", "volume")
    inbound = _add_fallback_cols(inbound, "weight_shipped", "raw__Quantity")

    if "origin_location_id" not in inbound.columns or "destination_location_id" not in inbound.columns:
        return {"mode": "inbound", "nodes": [], "lanes": [], "note": "Missing origin/destination columns in inbound shipments."}

    if metric == "volume":
        if "volume" in inbound.columns:
            value_col = "volume"
        elif "weight_shipped" in inbound.columns:
            value_col = "weight_shipped"
        elif "raw__Quantity" in inbound.columns:
            value_col = "raw__Quantity"
        else:
            value_col = None
    else:
        value_col = None
    lanes_df = _aggregate_lanes(inbound, "origin_location_id", "destination_location_id", value_col=value_col, top_n=top_n)

    # Load facility locations; IDs in shipments are sometimes numeric strings ("1928")
    # while location_master IDs may have leading text ("PL1001"). If no direct match,
    # fall back to a derived "plant code" like "PL1928".
    loc = _gold(project_id, "location_master", run_id, status_filter="all")
    points = _resolve_points(project_id, loc, id_col="location_id", name_col="location_name")

    def _loc_alias(x: str) -> List[str]:
        x = str(x)
        if x.isdigit():
            return [x, f"PL{x}"]
        return [x]

    lanes: List[Dict[str, Any]] = []
    node_ids = set()

    for _, r in lanes_df.iterrows():
        o = str(r["origin_location_id"])
        d = str(r["destination_location_id"])
        v = float(r["value"]) if pd.notna(r["value"]) else 0.0

        op = None
        for cand in _loc_alias(o):
            op = points.get(cand)
            if op:
                o = cand
                break

        dp = None
        for cand in _loc_alias(d):
            dp = points.get(cand)
            if dp:
                d = cand
                break
        # Only include lanes where both ends can be geocoded.
        if not op or not dp or op.get("lat") is None or dp.get("lat") is None:
            continue

        node_ids.add(o)
        node_ids.add(d)
        lanes.append({"origin": o, "destination": d, "value": v})

    nodes = [points[nid] for nid in node_ids if nid in points]
    return {"mode": "inbound", "nodes": nodes, "lanes": lanes, "metric": metric, "top_n": top_n}


def build_outbound_od_map(
    project_id: str,
    run_id: str,
    status_filter: str = "all",
    top_n: int = 150,
    metric: Literal["volume", "count"] = "volume",
) -> Dict[str, Any]:
    """
    Outbound = facility -> customer.

    Practical mapping in this app:
    - origin_location_id = shipping facility
    - destination_location_id may represent customer id in some sources; if so, we try:
        (a) customer_master.customer_id or location_master.location_id
      For robustness, we build both point maps and use whichever matches lane ids.
    """
    outbound = _gold(project_id, "outbound_shipment_history", run_id, status_filter)
    if outbound.empty:
        shipments = _gold(project_id, "shipment_history", run_id, status_filter)
        if not shipments.empty and "direction" in shipments.columns:
            outbound = shipments[shipments["direction"].astype(str).str.strip().str.lower() == "outbound"]
        else:
            outbound = shipments

    if outbound.empty:
        return {"mode": "outbound", "nodes": [], "lanes": [], "note": "No outbound shipment data found."}

    outbound = _add_fallback_cols(outbound, "origin_location_id", "destination_location_id", "volume")
    outbound = _add_fallback_cols(outbound, "weight_shipped", "raw__Quantity")

    if "origin_location_id" not in outbound.columns or "destination_location_id" not in outbound.columns:
        return {"mode": "outbound", "nodes": [], "lanes": [], "note": "Missing origin/destination columns in outbound shipments."}

    if metric == "volume":
        if "volume" in outbound.columns:
            value_col = "volume"
        elif "weight_shipped" in outbound.columns:
            value_col = "weight_shipped"
        elif "raw__Quantity" in outbound.columns:
            value_col = "raw__Quantity"
        else:
            value_col = None
    else:
        value_col = None
    lanes_df = _aggregate_lanes(outbound, "origin_location_id", "destination_location_id", value_col=value_col, top_n=top_n)

    loc = _gold(project_id, "location_master", run_id, status_filter="all")
    loc_points = _resolve_points(project_id, loc, id_col="location_id", name_col="location_name")

    def _loc_alias(x: str) -> List[str]:
        x = str(x)
        if x.isdigit():
            return [x, f"PL{x}"]
        return [x]

    customers = _gold(project_id, "customer_master", run_id, status_filter="all")
    cust_id_col = _first_existing_col(customers, ["customer_id", "destination_location_id", "location_id"])
    cust_name_col = _first_existing_col(customers, ["customer_name", "name"])
    cust_points = _resolve_points(project_id, customers, id_col=cust_id_col, name_col=cust_name_col) if cust_id_col else {}

    # Merge point registries; prefer customer metadata when ids overlap.
    points = {**loc_points, **cust_points}

    lanes: List[Dict[str, Any]] = []
    node_ids = set()

    for _, r in lanes_df.iterrows():
        o = str(r["origin_location_id"])
        d = str(r["destination_location_id"])
        v = float(r["value"]) if pd.notna(r["value"]) else 0.0

        op = None
        for cand in _loc_alias(o):
            op = points.get(cand) or loc_points.get(cand)
            if op:
                o = cand
                break

        dp = None
        for cand in _loc_alias(d):
            dp = points.get(cand) or cust_points.get(cand) or loc_points.get(cand)
            if dp:
                d = cand
                break

        if not op or not dp or op.get("lat") is None or dp.get("lat") is None:
            continue

        node_ids.add(o)
        node_ids.add(d)
        lanes.append({"origin": o, "destination": d, "value": v})

    nodes = [points.get(nid) or loc_points.get(nid) or cust_points.get(nid) for nid in node_ids]
    nodes = [n for n in nodes if n is not None]
    return {"mode": "outbound", "nodes": nodes, "lanes": lanes, "metric": metric, "top_n": top_n}
