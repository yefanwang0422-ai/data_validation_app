"""
Tests for optional/partial data sources (plan_v2.md extension):
the app must run successfully with any subset of the 8 datasets available,
using either SQL or uploaded-file sources per dataset, skipping the rest.
"""
import pandas as pd
import pytest

from app.config import (
    load_data_source_registry,
    save_data_source_registry,
    set_dataset_source_type,
)
from app.extraction import save_uploaded_file, get_uploaded_file_path
from app.pipeline import run_full_pipeline, load_gold
from app.sample_data import generate_customer_master, generate_location_master

TEST_PROJECT = "pytest_optional_sources_project"


def test_data_source_registry_defaults_to_none():
    registry = load_data_source_registry("brand_new_project_xyz")
    assert all(entry["source_type"] == "none" for entry in registry.values())


def test_set_dataset_source_type_persists():
    set_dataset_source_type(TEST_PROJECT, "customer_master", "file")
    registry = load_data_source_registry(TEST_PROJECT)
    assert registry["customer_master"]["source_type"] == "file"
    # reset for cleanliness
    set_dataset_source_type(TEST_PROJECT, "customer_master", "none")


def test_uploaded_file_is_saved_and_retrievable():
    df = generate_customer_master()
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    save_uploaded_file(TEST_PROJECT, "customer_master", "customers.csv", csv_bytes)
    path = get_uploaded_file_path(TEST_PROJECT, "customer_master")
    assert path is not None
    assert path.exists()
    reloaded = pd.read_csv(path)
    assert len(reloaded) == len(df)


def test_pipeline_runs_successfully_with_only_two_datasets_via_file_upload():
    """
    Configure only customer_master and location_master via file upload;
    everything else stays "none". The pipeline must complete successfully,
    processing only the configured datasets and skipping the rest.
    """
    project_id = "pytest_partial_data_project"

    customer_df = generate_customer_master()
    location_df = generate_location_master()

    save_uploaded_file(
        project_id, "customer_master", "customers.csv", customer_df.to_csv(index=False).encode("utf-8")
    )
    save_uploaded_file(
        project_id, "location_master", "locations.csv", location_df.to_csv(index=False).encode("utf-8")
    )

    set_dataset_source_type(project_id, "customer_master", "file")
    set_dataset_source_type(project_id, "location_master", "file")
    # All other 6 datasets remain "none" by default.

    summary = run_full_pipeline(project_id, use_sample_data=None)

    assert summary["run_id"]
    assert "customer_master" in summary["datasets"]
    assert "location_master" in summary["datasets"]
    assert summary["datasets"]["customer_master"]["skipped"] is False
    assert summary["datasets"]["location_master"]["skipped"] is False

    # The other 6 datasets should be marked skipped, not cause a failure.
    for skipped_ds in ["vendor_master", "product_master", "production_history",
                        "shipment_history", "shipment_cost", "inventory_history"]:
        assert skipped_ds in summary["skipped_datasets"]
        assert summary["datasets"][skipped_ds]["skipped"] is True

    # Gold data should exist for the configured datasets only.
    gold_customer = load_gold(project_id, "customer_master", summary["run_id"])
    assert len(gold_customer) == len(customer_df)

    with pytest.raises(FileNotFoundError):
        load_gold(project_id, "vendor_master", summary["run_id"])


def test_pipeline_falls_back_to_sample_data_when_nothing_configured():
    """
    A brand-new project with no SQL config and no uploads should still run
    successfully by falling back to synthetic sample data across all 8 datasets.
    """
    project_id = "pytest_fresh_project_no_sources"
    summary = run_full_pipeline(project_id, use_sample_data=None)
    assert summary["run_id"]
    assert len(summary["skipped_datasets"]) == 0
    assert summary["extraction_source"] == "sample"
    for ds in ["customer_master", "location_master", "vendor_master", "product_master"]:
        assert summary["datasets"][ds]["row_count"] > 0
