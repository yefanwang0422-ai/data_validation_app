"""
Python-Native Validation Views (plan_v2.md Section 7).

Every view function operates directly on Gold-layer DataFrames and accepts
a shared `status_filter` parameter: "all" | "validated" | "flagged" | "unresolved".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from app.pipeline import load_gold

STATUS_FILTER_VALUES = ("all", "validated", "flagged", "unresolved")


def _apply_status_filter(df: pd.DataFrame, status_filter: str) -> pd.DataFrame:
    if status_filter not in STATUS_FILTER_VALUES:
        raise ValueError(f"status_filter must be one of {STATUS_FILTER_VALUES}, got '{status_filter}'")
    if status_filter == "all" or "row_status" not in df.columns:
        return df
    if status_filter == "validated":
        return df[df["row_status"] == "valid"]
    if status_filter in ("flagged", "unresolved"):
        return df[df["row_status"] != "valid"]
    return df


def get_gold(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    return load_gold(project_id, dataset, run_id)


def get_raw_vs_validated(
    project_id: str, dataset: str, run_id: str, status_filter: str = "all"
) -> pd.DataFrame:
    """Side-by-side raw vs validated columns per record (Gold already carries both via lineage).
    Returns empty DataFrame if Gold data doesn't exist yet (Phase-1-only run)."""
    try:
        df = get_gold(project_id, dataset, run_id)
    except FileNotFoundError:
        return pd.DataFrame()
    return _apply_status_filter(df, status_filter)


def get_issue_flagged(
    project_id: str,
    dataset: str,
    run_id: str,
    issue_type: Optional[str] = None,
    severity: Optional[str] = None,
) -> pd.DataFrame:
    """Records with validation issues, optionally filtered by issue_type/severity."""
    issues_df = load_issue_log(project_id, run_id)
    if issues_df.empty or "dataset_name" not in issues_df.columns:
        return pd.DataFrame()
    issues_df = issues_df[issues_df["dataset_name"] == dataset]
    if issue_type:
        issues_df = issues_df[issues_df["issue_type"] == issue_type]
    if severity:
        issues_df = issues_df[issues_df["severity"] == severity]
    return issues_df


def get_cross_reference_exceptions(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    df = load_xref_exceptions(project_id, run_id)
    if df.empty or "dataset_name" not in df.columns:
        return pd.DataFrame()
    return df[df["dataset_name"] == dataset]


def get_ai_fill_review(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    df = load_review_queue(project_id, run_id)
    if df.empty or "dataset_name" not in df.columns:
        return pd.DataFrame()
    return df[df["dataset_name"] == dataset]


def get_dataset_quality_summary(project_id: str, dataset: str, run_id: str) -> Dict[str, Any]:
    try:
        df = get_gold(project_id, dataset, run_id)
    except FileNotFoundError:
        return {
            "dataset": dataset,
            "row_count": 0,
            "pct_valid": 0.0,
            "pct_needs_review": 0.0,
            "pct_invalid": 0.0,
            "ai_filled_count": 0,
            "note": "Gold data not yet available — run Phase 3 (Validate & Profile) to complete.",
        }
    total = len(df)
    if total == 0:
        return {"dataset": dataset, "row_count": 0}
    n_valid = int((df["row_status"] == "valid").sum())
    n_review = int((df["row_status"] == "needs_review").sum())
    n_invalid = int((df["row_status"] == "invalid").sum())
    ai_filled = 0
    review_df = get_ai_fill_review(project_id, dataset, run_id)
    if not review_df.empty and "applied" in review_df.columns:
        ai_filled = int(review_df["applied"].sum())

    return {
        "dataset": dataset,
        "row_count": total,
        "pct_valid": round(n_valid / total * 100, 1),
        "pct_needs_review": round(n_review / total * 100, 1),
        "pct_invalid": round(n_invalid / total * 100, 1),
        "ai_filled_count": ai_filled,
    }


# ---------------------------------------------------------------------------
# Log loaders (issue log / review queue / cross-reference exceptions)
# ---------------------------------------------------------------------------

from app.config import RUN_LOG_DIR  # noqa: E402


def _load_jsonl(path) -> pd.DataFrame:
    import json

    if not path.exists():
        return pd.DataFrame()
    records: List[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return pd.DataFrame(records)


def load_issue_log(project_id: str, run_id: str) -> pd.DataFrame:
    return _load_jsonl(RUN_LOG_DIR / project_id / f"{run_id}_issues.jsonl")


def load_review_queue(project_id: str, run_id: str) -> pd.DataFrame:
    return _load_jsonl(RUN_LOG_DIR / project_id / f"{run_id}_review_queue.jsonl")


def load_xref_exceptions(project_id: str, run_id: str) -> pd.DataFrame:
    return _load_jsonl(RUN_LOG_DIR / project_id / f"{run_id}_cross_reference_exceptions.jsonl")


def load_run_summary(project_id: str, run_id: str) -> dict:
    import json

    path = RUN_LOG_DIR / project_id / f"{run_id}_summary.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
