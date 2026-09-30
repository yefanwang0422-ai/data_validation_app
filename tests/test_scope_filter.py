"""Tests for app/scope_filter.py — user-defined business scope rule engine."""
import pandas as pd
import pytest

from app.scope_filter import (
    apply_scope_filters,
    apply_cascade_exclusions,
    build_excluded_key_lookup,
    save_dataset_scope_rules,
    get_dataset_scope_rules,
    load_scope_filters,
    scope_summary,
    _evaluate_rule,
)

PROJECT = "pytest_scope_filter_project"
DATASET = "shipment_history"


@pytest.fixture(autouse=True)
def cleanup():
    """Clear scope config for the test project before/after each test."""
    from app.scope_filter import _scope_config_path
    path = _scope_config_path(PROJECT)
    if path.exists():
        path.unlink()
    yield
    if path.exists():
        path.unlink()


def make_df():
    return pd.DataFrame({
        "shipment_id": ["S1", "S2", "S3", "S4"],
        "shipment_date": ["2024-01-15", "2023-06-01", "2024-08-20", None],
        "product_category": ["Electronics", "Furniture", "Chemicals", "Electronics"],
        "volume": [100, 200, 50, 300],
    })


def test_no_rules_all_in_scope():
    df = make_df()
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert result["scope_included"].all()
    assert result["scope_exclusion_reason"].isna().all()


def test_date_range_rule():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "date_range", "field": "shipment_date", "start": "2024-01-01", "end": "2024-12-31",
         "description": "2024 shipments only"}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    # S1 (2024-01-15) and S3 (2024-08-20) in scope; S2 (2023) and S4 (null date) excluded
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == True
    assert result.loc[result["shipment_id"] == "S3", "scope_included"].iloc[0] == True
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S4", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S2", "scope_exclusion_reason"].iloc[0] == "2024 shipments only"


def test_include_values_rule():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "include_values", "field": "product_category", "values": ["Electronics", "Chemicals"],
         "description": "In-scope categories"}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == True  # Electronics
    assert result.loc[result["shipment_id"] == "S3", "scope_included"].iloc[0] == True  # Chemicals
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == False  # Furniture


def test_exclude_values_rule():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "exclude_values", "field": "product_category", "values": ["Furniture"],
         "description": "Exclude furniture"}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == True


def test_numeric_range_rule():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "numeric_range", "field": "volume", "min": 60, "max": 250, "description": "Mid-volume shipments"}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == True  # 100
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == True  # 200
    assert result.loc[result["shipment_id"] == "S3", "scope_included"].iloc[0] == False  # 50 too low
    assert result.loc[result["shipment_id"] == "S4", "scope_included"].iloc[0] == False  # 300 too high


def test_multiple_rules_combine_with_and():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "date_range", "field": "shipment_date", "start": "2024-01-01", "end": "2024-12-31"},
        {"type": "include_values", "field": "product_category", "values": ["Electronics"]},
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    # Only S1 satisfies BOTH: 2024 date AND Electronics category
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == True
    assert result.loc[result["shipment_id"] == "S3", "scope_included"].iloc[0] == False  # 2024 but Chemicals


def test_missing_field_fails_safe():
    """If the configured field doesn't exist in the DataFrame, the rule should not incorrectly exclude data."""
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "include_values", "field": "nonexistent_field", "values": ["X"]}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert result["scope_included"].all()  # fails safe, nothing excluded


def test_scope_summary():
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "include_values", "field": "product_category", "values": ["Electronics"], "description": "Electronics only"}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    summary = scope_summary(result)
    assert summary["total"] == 4
    assert summary["included"] == 2  # S1, S4 are Electronics
    assert summary["excluded"] == 2
    assert "Electronics only" in summary["reasons"]
    assert summary["reasons"]["Electronics only"] == 2


def test_save_and_load_rules_roundtrip():
    rules = [
        {"type": "date_range", "field": "shipment_date", "start": "2024-01-01", "end": "2024-12-31"},
    ]
    save_dataset_scope_rules(PROJECT, DATASET, rules)
    loaded = get_dataset_scope_rules(PROJECT, DATASET)
    assert len(loaded) == 1
    assert loaded[0]["type"] == "date_range"
    assert loaded[0]["field"] == "shipment_date"
    assert "id" in loaded[0]  # auto-assigned id


def test_records_never_dropped():
    """Core guarantee: scope filtering must never remove rows, only flag them."""
    df = make_df()
    save_dataset_scope_rules(PROJECT, DATASET, [
        {"type": "include_values", "field": "product_category", "values": ["Electronics"]}
    ])
    result = apply_scope_filters(df, DATASET, PROJECT)
    assert len(result) == len(df)  # row count unchanged


# ---------------------------------------------------------------------------
# Cascade: master-data exclusions propagate to transactional datasets via FK
# ---------------------------------------------------------------------------

def test_build_excluded_key_lookup():
    product_master = pd.DataFrame({
        "product_id": ["A", "B", "C"],
        "scope_included": [False, True, True],
        "scope_exclusion_reason": ["Excluded category", None, None],
    })
    customer_master = pd.DataFrame({
        "customer_id": ["C1", "C2"],
        "scope_included": [True, True],
        "scope_exclusion_reason": [None, None],
    })
    lookup = build_excluded_key_lookup({
        "product_master": product_master,
        "customer_master": customer_master,
    })
    assert lookup == {"product_master": {"product_id": {"A"}}}  # customer_master has no exclusions, omitted


def test_cascade_exclusion_from_product_master():
    """Excluding Product A in product_master should cascade to shipment_history rows referencing it."""
    shipments = pd.DataFrame({
        "shipment_id": ["S1", "S2", "S3"],
        "product_id": ["A", "B", "A"],
        "scope_included": [True, True, True],
        "scope_exclusion_reason": [None, None, None],
    })
    lookup = {"product_master": {"product_id": {"A"}}}
    result = apply_cascade_exclusions(shipments, "shipment_history", lookup)

    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S3", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == True  # Product B unaffected

    reason_s1 = result.loc[result["shipment_id"] == "S1", "scope_exclusion_reason"].iloc[0]
    assert "cascade" in reason_s1.lower()
    assert "product_id" in reason_s1
    assert "'A'" in reason_s1
    assert "product_master" in reason_s1


def test_cascade_does_not_overwrite_direct_exclusion_reason():
    """If a row is already excluded by its own dataset's direct rule, cascade should not overwrite that reason."""
    shipments = pd.DataFrame({
        "shipment_id": ["S1"],
        "product_id": ["A"],
        "scope_included": [False],
        "scope_exclusion_reason": ["Direct rule: 2024 shipments only"],
    })
    lookup = {"product_master": {"product_id": {"A"}}}
    result = apply_cascade_exclusions(shipments, "shipment_history", lookup)
    # Reason should remain the original direct-rule reason, not be replaced by cascade text
    assert result["scope_exclusion_reason"].iloc[0] == "Direct rule: 2024 shipments only"
    assert result["scope_included"].iloc[0] == False


def test_cascade_no_lookup_is_noop():
    shipments = pd.DataFrame({
        "shipment_id": ["S1"],
        "product_id": ["A"],
        "scope_included": [True],
        "scope_exclusion_reason": [None],
    })
    result = apply_cascade_exclusions(shipments, "shipment_history", {})
    assert result["scope_included"].iloc[0] == True


def test_cascade_full_pipeline_integration():
    """
    End-to-end: exclude Product A via a product_master scope rule, run apply_scope_filters
    on product_master, build the lookup, then cascade onto shipment_history -- mirroring
    what app/pipeline.py._apply_scope_with_cascade does.
    """
    products = pd.DataFrame({"product_id": ["A", "B"], "product_category": ["Discontinued", "Active"]})
    save_dataset_scope_rules(PROJECT, "product_master", [
        {"type": "exclude_values", "field": "product_category", "values": ["Discontinued"],
         "description": "Exclude discontinued products"}
    ])
    scoped_products = apply_scope_filters(products, "product_master", PROJECT)
    assert scoped_products.loc[scoped_products["product_id"] == "A", "scope_included"].iloc[0] == False

    lookup = build_excluded_key_lookup({"product_master": scoped_products})
    assert lookup["product_master"]["product_id"] == {"A"}

    shipments = pd.DataFrame({
        "shipment_id": ["S1", "S2"],
        "product_id": ["A", "B"],
        "scope_included": [True, True],
        "scope_exclusion_reason": [None, None],
    })
    result = apply_cascade_exclusions(shipments, "shipment_history", lookup)
    assert result.loc[result["shipment_id"] == "S1", "scope_included"].iloc[0] == False
    assert result.loc[result["shipment_id"] == "S2", "scope_included"].iloc[0] == True
    reason = result.loc[result["shipment_id"] == "S1", "scope_exclusion_reason"].iloc[0]
    assert "product_master" in reason

    # Cleanup product_master rules created in this test
    from app.scope_filter import _scope_config_path
    path = _scope_config_path(PROJECT)
    if path.exists():
        path.unlink()
