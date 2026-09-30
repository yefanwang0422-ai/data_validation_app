"""
Data Profiling (plan_v2.md Section 2).

Lightweight, dependency-free profiler (no ydata-profiling requirement) that
produces a JSON-serializable profiling summary per dataset per run, plus
schema-drift detection against the previous run's stored schema snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config import RUN_LOG_DIR


def _profile_dir(project_id: str, dataset: str) -> Path:
    p = RUN_LOG_DIR / project_id / "profiles" / dataset
    p.mkdir(parents=True, exist_ok=True)
    return p


def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute a profiling summary for a DataFrame."""
    n_rows = len(df)
    columns_summary = {}
    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        summary = {
            "dtype": str(series.dtype),
            "null_count": null_count,
            "null_pct": round(null_count / n_rows * 100, 2) if n_rows else 0.0,
            "distinct_count": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series):
            non_null = series.dropna()
            if len(non_null):
                summary.update(
                    {
                        "min": float(non_null.min()),
                        "max": float(non_null.max()),
                        "mean": float(non_null.mean()),
                        "median": float(non_null.median()),
                    }
                )
        columns_summary[col] = summary

    return {
        "row_count": n_rows,
        "column_count": len(df.columns),
        "duplicate_row_count": int(df.duplicated().sum()),
        "columns": columns_summary,
    }


def detect_schema_drift(
    current_schema: Dict[str, str], previous_schema: Optional[Dict[str, str]]
) -> Dict[str, List[str]]:
    """Compare column-name/dtype sets between current and previous run."""
    if previous_schema is None:
        return {"new_columns": [], "removed_columns": [], "type_changes": []}

    current_cols = set(current_schema.keys())
    previous_cols = set(previous_schema.keys())

    new_columns = sorted(current_cols - previous_cols)
    removed_columns = sorted(previous_cols - current_cols)
    type_changes = sorted(
        col
        for col in current_cols & previous_cols
        if current_schema[col] != previous_schema[col]
    )
    return {
        "new_columns": new_columns,
        "removed_columns": removed_columns,
        "type_changes": type_changes,
    }


def _latest_previous_profile(project_id: str, dataset: str, exclude_run_id: str) -> Optional[dict]:
    prof_dir = _profile_dir(project_id, dataset)
    candidates = sorted(
        [p for p in prof_dir.glob("*.json") if exclude_run_id not in p.name],
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        return None
    with open(candidates[-1], "r", encoding="utf-8") as fh:
        return json.load(fh)


def run_profiling(df: pd.DataFrame, project_id: str, dataset: str, run_id: str) -> Dict[str, Any]:
    """Profile a Silver-layer DataFrame, detect drift vs previous run, persist report."""
    profile = profile_dataframe(df)
    current_schema = {col: str(df[col].dtype) for col in df.columns}

    previous = _latest_previous_profile(project_id, dataset, exclude_run_id=run_id)
    previous_schema = None
    if previous and "profile" in previous and "columns" in previous["profile"]:
        previous_schema = {col: info["dtype"] for col, info in previous["profile"]["columns"].items()}

    drift = detect_schema_drift(current_schema, previous_schema)

    report = {
        "project_id": project_id,
        "dataset": dataset,
        "run_id": run_id,
        "profile": profile,
        "schema_drift": drift,
    }

    out_path = _profile_dir(project_id, dataset) / f"{run_id}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    return report
