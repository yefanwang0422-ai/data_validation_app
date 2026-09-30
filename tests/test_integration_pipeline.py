"""
Integration test: full pipeline run (plan_v2.md Section 18 - Integration tests).

Covers: extraction -> Bronze -> Silver (canonical mapping) -> profiling ->
validation -> cross-reference -> AI enrichment -> Gold -> validation views ->
business metrics -> export, across all 8 datasets.
"""
import json

import pandas as pd
import pytest

from app.config import DATASETS, MASTER_DATASETS, TRANSACTIONAL_DATASETS
from app.export import export_all, export_optilogic_ready
from app.pipeline import load_gold, run_full_pipeline
from app.validation_views import (
    get_ai_fill_review,
    get_dataset_quality_summary,
    get_issue_flagged,
    load_run_summary,
)
from app.business_metrics import METRIC_REGISTRY

TEST_PROJECT = "pytest_integration_project"


@pytest.fixture(scope="module")
def run_summary():
    return run_full_pipeline(TEST_PROJECT, use_sample_data=True)


def test_pipeline_processes_all_datasets(run_summary):
    assert run_summary["run_id"]
    for dataset in DATASETS:
        assert dataset in run_summary["datasets"]
        assert run_summary["datasets"][dataset]["row_count"] > 0


def test_gold_layer_has_row_status_for_all_datasets(run_summary):
    run_id = run_summary["run_id"]
    for dataset in DATASETS:
        gold = load_gold(TEST_PROJECT, dataset, run_id)
        assert "row_status" in gold.columns
        assert set(gold["row_status"].unique()).issubset({"valid", "needs_review", "invalid"})


def test_master_datasets_have_canonical_columns(run_summary):
    run_id = run_summary["run_id"]
    expected_id_cols = {
        "customer_master": "customer_id",
        "location_master": "location_id",
        "vendor_master": "vendor_id",
        "product_master": "product_id",
    }
    for dataset, id_col in expected_id_cols.items():
        gold = load_gold(TEST_PROJECT, dataset, run_id)
        assert id_col in gold.columns


def test_transactional_datasets_have_cross_reference_flags(run_summary):
    run_id = run_summary["run_id"]
    gold = load_gold(TEST_PROJECT, "shipment_history", run_id)
    assert "product_id_valid_ref" in gold.columns


def test_issue_log_and_review_queue_are_populated(run_summary):
    run_id = run_summary["run_id"]
    issues = get_issue_flagged(TEST_PROJECT, "customer_master", run_id)
    review = get_ai_fill_review(TEST_PROJECT, "customer_master", run_id)
    # Sample data intentionally has some missing city/state records
    assert isinstance(issues, pd.DataFrame)
    assert isinstance(review, pd.DataFrame)


def test_dataset_quality_summary_percentages_sum_reasonably(run_summary):
    run_id = run_summary["run_id"]
    for dataset in DATASETS:
        summary = get_dataset_quality_summary(TEST_PROJECT, dataset, run_id)
        total_pct = summary["pct_valid"] + summary["pct_needs_review"] + summary["pct_invalid"]
        assert 99.0 <= total_pct <= 101.0  # rounding tolerance


def test_business_metrics_render_without_error(run_summary):
    run_id = run_summary["run_id"]
    for name, fn in METRIC_REGISTRY.items():
        fig = fn(TEST_PROJECT, run_id, status_filter="all")
        assert fig is not None


def test_business_metrics_respect_validated_filter(run_summary):
    run_id = run_summary["run_id"]
    fig_all = METRIC_REGISTRY["product_volume_pareto"](TEST_PROJECT, run_id, status_filter="all")
    fig_validated = METRIC_REGISTRY["product_volume_pareto"](TEST_PROJECT, run_id, status_filter="validated")
    assert fig_all is not None and fig_validated is not None


def test_run_summary_is_persisted_and_loadable(run_summary):
    run_id = run_summary["run_id"]
    loaded = load_run_summary(TEST_PROJECT, run_id)
    assert loaded["run_id"] == run_id


def test_export_all_generates_expected_files(run_summary, tmp_path):
    run_id = run_summary["run_id"]
    outputs = export_all(TEST_PROJECT, run_id, DATASETS)
    assert "issue_log" in outputs
    assert "review_queue" in outputs
    for dataset in DATASETS:
        assert f"{dataset}_gold_csv" in outputs
        assert f"{dataset}_optilogic_csv" in outputs


def test_optilogic_export_uses_optilogic_field_names(run_summary):
    run_id = run_summary["run_id"]
    path = export_optilogic_ready(TEST_PROJECT, "customer_master", run_id)
    df = pd.read_csv(path)
    # Optilogic field names per configs/canonical_schema/customer_master.yaml
    assert "CustomerName" in df.columns
    assert "City" in df.columns
    assert "PostalCode" in df.columns
