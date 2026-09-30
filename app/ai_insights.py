from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd

AI_API_BASE   = os.getenv("AI_API_BASE",   "https://api.ntth.ai/v1")
AI_APP_ID     = os.getenv("AI_APP_ID",     "6a08840a-6fde-43ef-8a5b-d3e62d0c9b71")
AI_APP_SECRET = os.getenv("AI_APP_SECRET", "_>NqtarwpNLo&cezMevZwnJnVXG]lu8MtaWB")
AI_MODEL      = os.getenv("AI_MODEL",      "6c26a584-a988-4fed-92ea-f6501429fab9")  # GPT-4o

# ── Data summarisation ────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def summarize_reporting_data(df: pd.DataFrame, scenario_a: str, scenario_b: str) -> Dict[str, Any]:
    """
    Aggregate the reporting DataFrame into a compact summary dict suitable for
    sending to the LLM.  Raw rows are never forwarded — only computed statistics.
    """
    if df.empty:
        return {"error": "No data available"}

    scenarios = [scenario_a, scenario_b]
    df = df[df["ScenarioName"].astype(str).isin(scenarios)].copy()

    def _num(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series([0.0] * len(df), index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["Cost($)"]    = _num("Cost($)")
    df["FlowVolume"] = _num("FlowVolume")

    # ── Cost breakdown per scenario ───────────────────────────────────────────
    cost_summary: Dict[str, Dict[str, float]] = {}
    for sc in scenarios:
        sdf = df[df["ScenarioName"].astype(str) == sc]
        costs_rows = sdf[sdf.get("Category", pd.Series(dtype=str)).astype(str).eq("Costs")] if "Category" in sdf.columns else pd.DataFrame()
        tnc_row = costs_rows[costs_rows.get("SubCategory", pd.Series(dtype=str)).astype(str).str.contains("totalnetwork", case=False, na=False)] if not costs_rows.empty else pd.DataFrame()
        tnc = float(tnc_row["Cost($)"].sum()) if not tnc_row.empty else float(sdf["Cost($)"].sum())

        op_rows = sdf[~sdf.get("Category", pd.Series(dtype=str)).astype(str).eq("Costs")] if "Category" in sdf.columns else sdf
        by_subcat: Dict[str, float] = {}
        if "CostSubCategory" in op_rows.columns:
            for subcat, grp in op_rows[op_rows["CostSubCategory"].astype(str).ne("-")].groupby("CostSubCategory"):
                by_subcat[str(subcat)] = float(grp["Cost($)"].sum())

        cost_summary[sc] = {"TotalNetworkCost": tnc, **by_subcat}

    # ── Flow volumes per scenario ─────────────────────────────────────────────
    flow_summary: Dict[str, Dict[str, float]] = {}
    for sc in scenarios:
        sdf = df[df["ScenarioName"].astype(str) == sc]
        entry: Dict[str, float] = {}
        if "SubCategory" in sdf.columns:
            for subcat in ["OutboundFlow", "InboundFlow", "TransferFlow", "ProductionFlow", "DemandVolume"]:
                val = float(sdf[sdf["SubCategory"].astype(str) == subcat]["FlowVolume"].sum())
                if val != 0:
                    entry[subcat] = val
        flow_summary[sc] = entry

    # ── Service level proxy ───────────────────────────────────────────────────
    sl_summary: Dict[str, float] = {}
    if "Category" in df.columns and "SubCategory" in df.columns:
        for sc in scenarios:
            sdf = df[df["ScenarioName"].astype(str) == sc]
            demand    = float(sdf[sdf["SubCategory"].astype(str) == "DemandVolume"]["FlowVolume"].sum())
            fulfilled = float(sdf[sdf["SubCategory"].astype(str) == "OutboundFlow"]["FlowVolume"].sum())
            sl_summary[sc] = round(fulfilled / demand * 100, 2) if demand > 0 else 0.0

    # ── Top facilities by cost ────────────────────────────────────────────────
    top_facilities: List[Dict[str, Any]] = []
    if "OriginName" in df.columns:
        fac = (df[df["ScenarioName"].astype(str) == scenario_a]
               .groupby("OriginName", as_index=False)["Cost($)"].sum()
               .sort_values("Cost($)", ascending=False)
               .head(10))
        top_facilities = fac.rename(columns={"Cost($)": "TotalCost"}).to_dict("records")

    # ── Cost delta between scenarios ──────────────────────────────────────────
    delta_summary: Dict[str, float] = {}
    cost_a = cost_summary.get(scenario_a, {})
    cost_b = cost_summary.get(scenario_b, {})
    all_keys = set(cost_a.keys()) | set(cost_b.keys())
    for k in all_keys:
        d = _safe_float(cost_a.get(k, 0)) - _safe_float(cost_b.get(k, 0))
        if abs(d) > 1:
            delta_summary[k] = round(d, 2)

    # ── Geographic spread ─────────────────────────────────────────────────────
    geo_stats: Dict[str, Any] = {}
    if "OriginState" in df.columns:
        states = df[df["ScenarioName"].astype(str) == scenario_a]["OriginState"].dropna().unique().tolist()
        geo_stats["originStates"] = [s for s in states if s != "-"][:20]
    if "DestinationState" in df.columns:
        dst_states = df[df["ScenarioName"].astype(str) == scenario_a]["DestinationState"].dropna().unique().tolist()
        geo_stats["destinationStates"] = [s for s in dst_states if s != "-"][:20]

    # ── Unique counts ─────────────────────────────────────────────────────────
    counts: Dict[str, int] = {}
    if "OriginName" in df.columns:
        counts["facilities"] = int(df[df["ScenarioName"].astype(str) == scenario_a]["OriginName"].nunique())
    if "DestinationName" in df.columns:
        counts["customers"] = int(df[df["ScenarioName"].astype(str) == scenario_a]["DestinationName"].nunique())
    if "Resource" in df.columns:
        counts["products"] = int(df[df["ScenarioName"].astype(str) == scenario_a]["Resource"].replace("-", pd.NA).dropna().nunique())

    return {
        "scenarioA": scenario_a,
        "scenarioB": scenario_b,
        "costs": cost_summary,
        "flows": flow_summary,
        "serviceLevel": sl_summary,
        "costDelta": delta_summary,
        "topFacilities": top_facilities,
        "networkCounts": counts,
        "geoSpread": geo_stats,
    }


# ── AI API call ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert supply chain network analyst and data visualisation specialist.
You will be given a statistical summary of a supply chain scenario comparison and must produce a
professional executive insights dashboard specification in **strict JSON**.

Return ONLY valid JSON — no markdown, no commentary, no code fences.

The JSON must have exactly this structure:
{
  "executive_summary": "<3-4 sentence paragraph summarising the key finding of the comparison>",
  "key_findings": ["<finding 1>", "<finding 2>", "<finding 3>", "<finding 4>", "<finding 5>"],
  "recommendations": ["<action 1>", "<action 2>", "<action 3>"],
  "kpis": [
    {
      "label": "<metric name>",
      "value_a": <number>,
      "value_b": <number>,
      "unit": "<$ or % or units>",
      "commentary": "<one sentence insight>"
    }
  ],
  "charts": [
    {
      "title": "<chart title>",
      "insight": "<one sentence explaining what this chart reveals>",
      "data": [<Plotly trace objects as JSON>],
      "layout": {<Plotly layout object as JSON>}
    }
  ]
}

Guidelines:
- Include 4-6 KPIs covering: total network cost, transportation cost, inventory cost, service level, production volume, top facility cost.
- Include 4-5 charts. Choose the most insightful chart types from: bar, waterfall, pie/donut, scatter, funnel, indicator. Use Plotly.js trace format.
- Charts must use professional colours: blues (#2563eb, #0891b2), purples (#7c3aed), greens (#059669), reds (#dc2626), ambers (#d97706).
- All monetary values in the charts should be formatted in $M (millions) where appropriate.
- Scenario A is the primary / reference scenario. Scenario B is the alternative / comparison.
- Write in executive language — be specific, quantitative, and actionable.
- The dashboard will be shown to supply chain executives who need to decide which scenario is better.
"""


def _get_auth_token() -> str:
    resp = httpx.post(
        f"{AI_API_BASE}/auth/appLogin",
        json={"id": AI_APP_ID, "secret": AI_APP_SECRET},
        verify=False,
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"AI gateway auth failed {resp.status_code}: {resp.text[:300]}")
    token = resp.json().get("token")
    if not token:
        raise RuntimeError("AI gateway auth returned no token.")
    return token


def _get_workspace_id(token: str) -> Optional[str]:
    headers = {"Authorization": token, "Content-Type": "application/json"}
    resp = httpx.get(
        f"{AI_API_BASE}/workspace/workspaces",
        headers=headers,
        verify=False,
        timeout=30.0,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    items = (
        data.get("items")
        or data.get("data")
        or data.get("workspaces")
        or (data if isinstance(data, list) else [])
    )
    if not items:
        return None
    w = items[0]
    return str(w.get("id") or w.get("_id") or "")


def _call_via_workspace(token: str, workspace_id: str, request_body: Dict[str, Any]) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": token}
    with httpx.Client(timeout=120.0, verify=False) as client:
        resp = client.post(
            f"{AI_API_BASE}/workspace/workspaces/{workspace_id}/thread/run",
            headers=headers, json=request_body,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"workspace/thread/run {resp.status_code}: {resp.text[:400]}")
    body = resp.json()
    return body.get("content", "")


def _call_via_chat(token: str, request_body: Dict[str, Any]) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": token}
    chat_body = {
        "id":       request_body["id"],
        "modelId":  request_body["modelId"],
        "stream":   False,
        "messages": request_body["messages"],
    }
    with httpx.Client(timeout=120.0, verify=False) as client:
        resp = client.post(f"{AI_API_BASE}/chat", headers=headers, json=chat_body)
    if resp.status_code != 200:
        raise RuntimeError(f"chat {resp.status_code}: {resp.text[:400]}")
    body = resp.json()
    return body.get("content", "")


def call_ai_gateway(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Authenticate -> call GPT-4o via the NTT AI gateway.
    Tries workspace/thread/run first; falls back to /chat.
    """
    user_message = (
        "Here is the supply chain scenario comparison data summary:\n\n"
        + json.dumps(summary, indent=2)
        + "\n\nGenerate the executive insights dashboard JSON as specified."
    )

    token = _get_auth_token()
    request_body = {
        "id":       str(uuid.uuid4()),
        "modelId":  AI_MODEL,
        "stream":   False,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }

    raw_text = ""
    last_error = ""

    workspace_id = _get_workspace_id(token)
    if workspace_id:
        try:
            raw_text = _call_via_workspace(token, workspace_id, request_body)
        except RuntimeError as e:
            last_error = str(e)

    if not raw_text:
        try:
            raw_text = _call_via_chat(token, request_body)
        except RuntimeError as e:
            last_error = str(e)

    if not raw_text:
        raise RuntimeError(f"All AI endpoints failed. Last error: {last_error}")

    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:])
    if raw_text.endswith("```"):
        raw_text = raw_text[:raw_text.rfind("```")]

    try:
        dashboard_spec = json.loads(raw_text.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI response was not valid JSON: {exc}\n\nRaw: {raw_text[:800]}")

    return dashboard_spec


def generate_ai_dashboard(df: pd.DataFrame, scenario_a: str, scenario_b: str) -> Dict[str, Any]:
    """Full pipeline: summarise -> call AI -> return dashboard spec."""
    summary = summarize_reporting_data(df, scenario_a, scenario_b)
    spec    = call_ai_gateway(summary)
    spec["dataSummary"] = summary
    return spec


# ── Root-cause enriched summary for chat ──────────────────────────────────────

def build_rootcause_summary(df: pd.DataFrame, scenario_a: str, scenario_b: str) -> Dict[str, Any]:
    """Build a richer summary for root-cause chatbot answers."""
    base = summarize_reporting_data(df, scenario_a, scenario_b)
    if "error" in base:
        return base

    scenarios = [scenario_a, scenario_b]
    df = df[df["ScenarioName"].astype(str).isin(scenarios)].copy()

    def _num(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series([0.0] * len(df), index=df.index)
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["Cost($)"]    = _num("Cost($)")
    df["FlowVolume"] = _num("FlowVolume")

    def _delta_by(group_col: str, value_col: str, top_n: int = 20) -> List[Dict[str, Any]]:
        if group_col not in df.columns:
            return []
        pivot = (
            df[df[group_col].astype(str).ne("-")]
            .groupby(["ScenarioName", group_col])[value_col]
            .sum()
            .unstack("ScenarioName")
            .fillna(0.0)
        )
        a_col = scenario_a if scenario_a in pivot.columns else None
        b_col = scenario_b if scenario_b in pivot.columns else None
        if not a_col and not b_col:
            return []
        pivot["val_a"] = pivot[a_col] if a_col else 0.0
        pivot["val_b"] = pivot[b_col] if b_col else 0.0
        pivot["delta"] = pivot["val_a"] - pivot["val_b"]
        pivot["abs_delta"] = pivot["delta"].abs()
        top = pivot.nlargest(top_n, "abs_delta").reset_index()
        return [
            {group_col: str(r[group_col]), "val_a": round(r["val_a"], 2),
             "val_b": round(r["val_b"], 2), "delta": round(r["delta"], 2)}
            for _, r in top.iterrows()
        ]

    facility_cost_deltas   = _delta_by("OriginName", "Cost($)", top_n=20)
    facility_volume_deltas = _delta_by("OriginName", "FlowVolume", top_n=20)
    cost_subcat_deltas     = _delta_by("CostSubCategory", "Cost($)", top_n=20)
    mode_deltas            = _delta_by("Mode", "FlowVolume", top_n=10)
    mode_cost_deltas       = _delta_by("Mode", "Cost($)", top_n=10)
    resource_cost_deltas   = _delta_by("Resource", "Cost($)", top_n=15)
    resource_volume_deltas = _delta_by("Resource", "FlowVolume", top_n=15)
    time_cost_deltas       = _delta_by("TimePeriod", "Cost($)", top_n=20)
    destination_deltas     = _delta_by("DestinationName", "Cost($)", top_n=15)
    origin_type_deltas     = _delta_by("OriginType", "Cost($)", top_n=10)
    dest_type_deltas       = _delta_by("DestinationType", "Cost($)", top_n=10)
    subcat_deltas          = _delta_by("SubCategory", "Cost($)", top_n=15)

    lane_deltas: List[Dict[str, Any]] = []
    if "OriginName" in df.columns and "DestinationName" in df.columns:
        df["_lane"] = df["OriginName"].astype(str) + " -> " + df["DestinationName"].astype(str)
        lane_deltas = _delta_by("_lane", "Cost($)", top_n=15)

    distance_deltas: List[Dict[str, Any]] = []
    if "Distance(Kms)" in df.columns and "OriginName" in df.columns and "DestinationName" in df.columns:
        df["_dist_lane"] = df["OriginName"].astype(str) + " -> " + df["DestinationName"].astype(str)
        df["Distance(Kms)"] = _num("Distance(Kms)")
        dist_pivot = (
            df.groupby(["ScenarioName", "_dist_lane"])["Distance(Kms)"]
            .mean()
            .unstack("ScenarioName")
            .fillna(0.0)
        )
        a_c = scenario_a if scenario_a in dist_pivot.columns else None
        b_c = scenario_b if scenario_b in dist_pivot.columns else None
        if a_c and b_c:
            dist_pivot["delta"] = dist_pivot[a_c] - dist_pivot[b_c]
            dist_pivot["abs_delta"] = dist_pivot["delta"].abs()
            top_d = dist_pivot.nlargest(15, "abs_delta").reset_index()
            distance_deltas = [
                {"lane": str(r["_dist_lane"]),
                 "dist_a": round(r[a_c], 1), "dist_b": round(r[b_c], 1),
                 "delta_km": round(r["delta"], 1)}
                for _, r in top_d.iterrows()
            ]

    return {
        **base,
        "rootCause": {
            "costSubCategoryDeltas":  cost_subcat_deltas,
            "facilityDeltas":         {"cost": facility_cost_deltas, "volume": facility_volume_deltas},
            "laneDeltas":             lane_deltas,
            "distanceDeltas":         distance_deltas,
            "modeDeltas":             {"volume": mode_deltas, "cost": mode_cost_deltas},
            "resourceDeltas":         {"cost": resource_cost_deltas, "volume": resource_volume_deltas},
            "timePeriodDeltas":       time_cost_deltas,
            "destinationDeltas":      destination_deltas,
            "originTypeDeltas":       origin_type_deltas,
            "destinationTypeDeltas":  dest_type_deltas,
            "subCategoryDeltas":      subcat_deltas,
        },
    }


# ── Chat system prompt ─────────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = """You are an expert supply chain network analyst assistant.

CRITICAL FORMATTING RULES:
- Do NOT use ordered lists (no lines starting with "1." or "1)"). Use '-' bullets only.
- For section headers, use plain text like "Outbound Flow:" (no leading numbers).

You are helping a supply chain analyst understand differences between two supply chain scenarios.
Answer questions clearly and quantitatively. When asked why a KPI changed, drill through
root-cause data and explain the primary drivers with specific numbers.

Root-cause analysis structure:
- State the total delta first (e.g. "Total network cost increased by $2.6M (+8.3%)")
- List primary drivers ranked by absolute impact with specific values
- For each driver, explain the mechanism
- End with a "Data used" section listing dimensions consulted

Guidelines:
- Be specific and quantitative. Use $, %, units.
- Format large numbers: $1.4M, 18%, 650K units
- Keep answers concise but complete
- Reference actual values from the data summary
"""


def answer_chat_question(
    df: pd.DataFrame,
    scenario_a: str,
    scenario_b: str,
    messages: List[Dict[str, str]],
) -> str:
    """
    Given the reporting DataFrame and conversation history, return the AI's next answer.
    """
    summary = build_rootcause_summary(df, scenario_a, scenario_b)

    data_context = (
        f"Here is the supply chain scenario comparison data summary for "
        f"**{scenario_a}** (Scenario A) vs **{scenario_b}** (Scenario B):\n\n"
        + json.dumps(summary, indent=2)
    )

    api_messages: List[Dict[str, str]] = [
        {"role": "system",    "content": _CHAT_SYSTEM_PROMPT},
        {"role": "user",      "content": data_context},
        {"role": "assistant", "content": (
            f"Understood. I have loaded the scenario comparison data for "
            f"**{scenario_a}** vs **{scenario_b}**. What would you like to know?"
        )},
    ]

    for msg in messages:
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    token = _get_auth_token()
    request_body = {
        "id":       str(uuid.uuid4()),
        "modelId":  AI_MODEL,
        "stream":   False,
        "messages": api_messages,
    }

    raw_text = ""
    last_error = ""

    workspace_id = _get_workspace_id(token)
    if workspace_id:
        try:
            raw_text = _call_via_workspace(token, workspace_id, request_body)
        except RuntimeError as e:
            last_error = str(e)

    if not raw_text:
        try:
            raw_text = _call_via_chat(token, request_body)
        except RuntimeError as e:
            last_error = str(e)

    if not raw_text:
        raise RuntimeError(f"All AI endpoints failed. Last error: {last_error}")

    return raw_text.strip()
