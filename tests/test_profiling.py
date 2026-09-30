"""Unit tests for the profiling module (plan_v2.md Section 2)."""
import pandas as pd

from app.profiling import detect_schema_drift, profile_dataframe


def test_profile_dataframe_computes_null_and_distinct_counts():
    df = pd.DataFrame({"a": [1, 2, None, 4], "b": ["x", "x", "y", None]})
    profile = profile_dataframe(df)
    assert profile["row_count"] == 4
    assert profile["columns"]["a"]["null_count"] == 1
    assert profile["columns"]["b"]["null_count"] == 1
    assert profile["columns"]["b"]["distinct_count"] == 2


def test_profile_dataframe_numeric_stats():
    df = pd.DataFrame({"weight": [10.0, 20.0, 30.0]})
    profile = profile_dataframe(df)
    stats = profile["columns"]["weight"]
    assert stats["min"] == 10.0
    assert stats["max"] == 30.0
    assert stats["mean"] == 20.0


def test_schema_drift_detects_new_and_removed_columns():
    current = {"a": "int64", "b": "object", "c": "float64"}
    previous = {"a": "int64", "b": "object", "d": "object"}
    drift = detect_schema_drift(current, previous)
    assert drift["new_columns"] == ["c"]
    assert drift["removed_columns"] == ["d"]
    assert drift["type_changes"] == []


def test_schema_drift_detects_type_change():
    current = {"a": "float64"}
    previous = {"a": "int64"}
    drift = detect_schema_drift(current, previous)
    assert drift["type_changes"] == ["a"]


def test_schema_drift_no_previous_run_returns_empty():
    drift = detect_schema_drift({"a": "int64"}, None)
    assert drift == {"new_columns": [], "removed_columns": [], "type_changes": []}
