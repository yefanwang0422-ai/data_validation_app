"""
Business Validation / Analytics Views (plan_v2.md Section 7a).

Every metric function accepts a `status_filter` ("all" | "validated" | "flagged" | "unresolved")
so business charts can be sliced by validation state.

Charts are designed to work with whatever Gold data is available:
- Shipment-based charts try all three shipment datasets (outbound, inbound, combined)
- Master-data charts (product, customer, inventory) work independently of shipment data
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.pipeline import load_gold
from app.validation_views import _apply_status_filter


# Alternative raw column names to try when canonical columns are missing
_RAW_FALLBACKS = {
    "volume": ["raw__Quantity", "raw__Qty", "raw__quantity", "raw__qty", "raw__Volume", "raw__volume"],
    "state": ["raw__ST", "raw__State", "raw__state", "raw__Province", "raw__province"],
    "shipment_mode": ["raw__Mode", "raw__mode", "raw__TransMode"],
    "destination_location_id": ["raw__ShipToLoc", "raw__ship_to_loc"],
    "origin_location_id": ["raw__OriginLoc", "raw__origin_loc"],
    "product_category": ["raw__Cat", "raw__cat", "raw__Category", "raw__category"],
    "quantity_on_hand": ["raw__OnHandQty", "raw__on_hand_qty"],
}


def _apply_scope_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Restrict to records that pass user-defined business scope rules.
    If scope_included column isn't present (no scope rules configured / older run), no-op."""
    if df.empty or "scope_included" not in df.columns:
        return df
    return df[df["scope_included"]]


def _gold(project_id: str, dataset: str, run_id: str, status_filter: str) -> pd.DataFrame:
    """Load Gold data gracefully — returns empty DataFrame if not available.
    Applies scope filter (business in-scope records only) before the data-quality status_filter."""
    try:
        df = load_gold(project_id, dataset, run_id)
        df = _apply_scope_filter(df)
        return _apply_status_filter(df, status_filter)
    except FileNotFoundError:
        return pd.DataFrame()


def _coalesce_col(df: pd.DataFrame, canonical: str) -> pd.Series:
    """Return canonical column, falling back to known raw column alternatives."""
    if canonical in df.columns:
        return df[canonical]
    for alt in _RAW_FALLBACKS.get(canonical, []):
        if alt in df.columns:
            return df[alt].rename(canonical)
    return None


def _best_shipment(project_id: str, run_id: str, status_filter: str,
                   prefer: Optional[str] = None) -> pd.DataFrame:
    """
    Load the best available shipment dataset.
    Priority: prefer (if specified) → outbound_shipment_history → inbound_shipment_history → shipment_history.
    Returns the first non-empty DataFrame found.
    """
    candidates = []
    if prefer:
        candidates.append(prefer)
    candidates += ["outbound_shipment_history", "inbound_shipment_history", "shipment_history"]
    # Remove duplicates while preserving order
    seen = set()
    ordered = [c for c in candidates if not (c in seen or seen.add(c))]
    for ds in ordered:
        df = _gold(project_id, ds, run_id, status_filter)
        if not df.empty:
            return df
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Shipment-based metrics (use best available shipment dataset)
# ---------------------------------------------------------------------------

def _add_fallback_cols(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """Add fallback columns to a copy of df, using raw__ alternatives where canonical is missing."""
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            series = _coalesce_col(df, col)
            if series is not None:
                if col in ("volume", "quantity_on_hand", "cost_amount"):
                    try:
                        df[col] = pd.to_numeric(series)
                    except (ValueError, TypeError):
                        df[col] = pd.to_numeric(series, errors="coerce")
                else:
                    df[col] = series
    return df


def customer_volume_distribution(
    project_id: str, run_id: str, status_filter: str = "all", top_n: int = 20
) -> go.Figure:
    """Bar chart: customers ranked by outbound shipped volume."""
    shipments = _best_shipment(project_id, run_id, status_filter, prefer="outbound_shipment_history")
    if shipments.empty:
        return go.Figure()

    shipments = _add_fallback_cols(shipments, "volume", "destination_location_id")
    if "destination_location_id" not in shipments.columns or "volume" not in shipments.columns:
        return go.Figure()

    # Filter to outbound direction if direction column exists
    if "direction" in shipments.columns:
        outbound = shipments[shipments["direction"].str.strip().str.lower() == "outbound"]
        if outbound.empty:
            outbound = shipments  # fallback to all if filter gives nothing
    else:
        outbound = shipments

    vol = pd.to_numeric(outbound["volume"], errors="coerce")
    if vol.isna().all():
        return go.Figure()
    outbound = outbound.copy()
    outbound["volume"] = vol

    agg = (
        outbound.groupby("destination_location_id")["volume"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .reset_index()
    )
    if agg.empty:
        return go.Figure()
    fig = px.bar(
        agg, x="destination_location_id", y="volume",
        title=f"Customer Distribution by Shipped Volume (Top {top_n})",
        labels={"destination_location_id": "Customer / Destination", "volume": "Total Volume"},
    )
    return fig


def product_volume_pareto(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Pareto chart: product volume (bar) + cumulative % (line)."""
    shipments = _best_shipment(project_id, run_id, status_filter)
    if shipments.empty:
        return go.Figure()

    shipments = _add_fallback_cols(shipments, "volume")
    if "product_id" not in shipments.columns or "volume" not in shipments.columns:
        return go.Figure()

    shipments["volume"] = pd.to_numeric(shipments["volume"], errors="coerce")
    agg = shipments.dropna(subset=["volume"]).groupby("product_id")["volume"].sum().sort_values(ascending=False).reset_index()
    if agg.empty:
        return go.Figure()
    agg["cumulative_pct"] = agg["volume"].cumsum() / agg["volume"].sum() * 100

    fig = go.Figure()
    fig.add_bar(x=agg["product_id"], y=agg["volume"], name="Volume")
    fig.add_trace(
        go.Scatter(
            x=agg["product_id"], y=agg["cumulative_pct"], name="Cumulative %",
            yaxis="y2", mode="lines+markers", line=dict(color="red"),
        )
    )
    fig.update_layout(
        title="Product Volume Pareto Chart",
        yaxis=dict(title="Volume"),
        yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 110]),
        xaxis=dict(title="Product"),
    )
    return fig


def inbound_flow(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Inbound flow by destination location."""
    inbound = _gold(project_id, "inbound_shipment_history", run_id, status_filter)
    if inbound.empty:
        shipments = _gold(project_id, "shipment_history", run_id, status_filter)
        if not shipments.empty and "direction" in shipments.columns:
            inbound = shipments[shipments["direction"].str.strip().str.lower() == "inbound"]
        else:
            inbound = shipments

    if inbound.empty:
        return go.Figure()
    inbound = _add_fallback_cols(inbound, "volume", "destination_location_id")
    if "destination_location_id" not in inbound.columns or "volume" not in inbound.columns:
        return go.Figure()
    inbound["volume"] = pd.to_numeric(inbound["volume"], errors="coerce")
    agg = inbound.dropna(subset=["volume"]).groupby("destination_location_id")["volume"].sum().sort_values(ascending=False).reset_index()
    if agg.empty:
        return go.Figure()
    fig = px.bar(agg, x="destination_location_id", y="volume",
                 title="Inbound Flow by Destination Location",
                 labels={"destination_location_id": "Location", "volume": "Inbound Volume"})
    return fig


def outbound_flow(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Outbound flow by origin location."""
    outbound = _gold(project_id, "outbound_shipment_history", run_id, status_filter)
    if outbound.empty:
        shipments = _gold(project_id, "shipment_history", run_id, status_filter)
        if not shipments.empty and "direction" in shipments.columns:
            outbound = shipments[shipments["direction"].str.strip().str.lower() == "outbound"]
        else:
            outbound = shipments

    if outbound.empty:
        return go.Figure()
    outbound = _add_fallback_cols(outbound, "volume", "origin_location_id")
    if "origin_location_id" not in outbound.columns or "volume" not in outbound.columns:
        return go.Figure()
    outbound["volume"] = pd.to_numeric(outbound["volume"], errors="coerce")
    agg = outbound.dropna(subset=["volume"]).groupby("origin_location_id")["volume"].sum().sort_values(ascending=False).reset_index()
    if agg.empty:
        return go.Figure()
    fig = px.bar(agg, x="origin_location_id", y="volume",
                 title="Outbound Flow by Origin Location",
                 labels={"origin_location_id": "Location", "volume": "Outbound Volume"})
    return fig


def total_spending(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Total spending aggregated by vendor (carrier), from shipment_cost."""
    costs = _gold(project_id, "shipment_cost", run_id, status_filter)
    if costs.empty:
        return go.Figure()
    costs = _add_fallback_cols(costs, "cost_amount")
    if "cost_amount" not in costs.columns:
        return go.Figure()

    costs["cost_amount"] = pd.to_numeric(costs["cost_amount"], errors="coerce")
    group_col = next((c for c in ["vendor_id", "carrier_id"] if c in costs.columns), None)
    if group_col is None:
        return go.Figure()
    agg = costs.dropna(subset=["cost_amount"]).groupby(group_col)["cost_amount"].sum().sort_values(ascending=False).reset_index()
    if agg.empty:
        return go.Figure()
    fig = px.bar(agg, x=group_col, y="cost_amount",
                 title="Total Spending by Vendor/Carrier",
                 labels={group_col: "Vendor", "cost_amount": "Total Cost"})
    return fig


def mode_split(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Transportation mode split by volume."""
    shipments = _best_shipment(project_id, run_id, status_filter)
    if shipments.empty:
        return go.Figure()
    shipments = _add_fallback_cols(shipments, "volume", "shipment_mode")
    if "shipment_mode" not in shipments.columns or "volume" not in shipments.columns:
        return go.Figure()
    shipments["volume"] = pd.to_numeric(shipments["volume"], errors="coerce")
    agg = shipments.dropna(subset=["volume"]).groupby("shipment_mode")["volume"].sum().reset_index()
    if agg.empty:
        return go.Figure()
    fig = px.pie(agg, names="shipment_mode", values="volume", title="Transportation Mode Split (by Volume)")
    return fig


# ---------------------------------------------------------------------------
# Master-data charts (work without any shipment data)
# ---------------------------------------------------------------------------

def product_category_breakdown(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Bar chart: product count by category from product_master."""
    products = _gold(project_id, "product_master", run_id, status_filter)
    if products.empty:
        return go.Figure()

    cat_col = next((c for c in ["product_category", "product_family", "product_group"] if c in products.columns), None)
    if cat_col is None:
        return go.Figure()

    agg = products.groupby(cat_col).size().sort_values(ascending=False).reset_index(name="count")
    fig = px.bar(
        agg, x=cat_col, y="count",
        title="Product Count by Category",
        labels={cat_col: "Category", "count": "Number of SKUs"},
    )
    return fig


def customer_geographic_distribution(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Bar chart: customer count by state from customer_master."""
    customers = _gold(project_id, "customer_master", run_id, status_filter)
    if customers.empty:
        return go.Figure()

    state_col = "state" if "state" in customers.columns else None
    if state_col is None:
        # Fall back to region
        state_col = "region" if "region" in customers.columns else None
    if state_col is None:
        return go.Figure()

    agg = customers.groupby(state_col).size().sort_values(ascending=False).reset_index(name="count")
    fig = px.bar(
        agg, x=state_col, y="count",
        title="Customer Count by State/Region",
        labels={state_col: "State / Region", "count": "Number of Customers"},
    )
    return fig


def inventory_on_hand_by_location(project_id: str, run_id: str, status_filter: str = "all") -> go.Figure:
    """Bar chart: total on-hand inventory by location from inventory_history."""
    inventory = _gold(project_id, "inventory_history", run_id, status_filter)
    if inventory.empty or "quantity_on_hand" not in inventory.columns:
        return go.Figure()

    loc_col = next((c for c in ["location_id", "warehouse_id"] if c in inventory.columns), None)
    if loc_col is None:
        return go.Figure()

    agg = inventory.groupby(loc_col)["quantity_on_hand"].sum().sort_values(ascending=False).reset_index()
    fig = px.bar(
        agg, x=loc_col, y="quantity_on_hand",
        title="Total On-Hand Inventory by Location",
        labels={loc_col: "Location", "quantity_on_hand": "On-Hand Quantity"},
    )
    return fig


METRIC_REGISTRY = {
    # Shipment-based
    "customer_volume_distribution": customer_volume_distribution,
    "product_volume_pareto": product_volume_pareto,
    "inbound_flow": inbound_flow,
    "outbound_flow": outbound_flow,
    "total_spending": total_spending,
    "mode_split": mode_split,
    # Master-data (work without shipment data)
    "product_category_breakdown": product_category_breakdown,
    "customer_geographic_distribution": customer_geographic_distribution,
    "inventory_on_hand_by_location": inventory_on_hand_by_location,
}
