"""Unit tests for the validation & cross-reference engine (plan_v2.md Sections 3 & 5)."""
import pandas as pd

from app.validation import cross_reference_check, flag_in_scope_products, validate_dataset


def test_missing_mandatory_field_flags_invalid():
    df = pd.DataFrame(
        {
            "customer_id": ["C1", "C2"],
            "customer_name": ["Acme", "Beta"],
            "city": ["Chicago", None],
            "state": ["IL", None],
            "postal_code": ["60601", None],
            "country": ["USA", "USA"],
            "latitude": [41.8, None],
            "longitude": [-87.6, None],
        }
    )
    gold, issues = validate_dataset(df, "customer_master", "run_test")

    assert gold.loc[gold["customer_id"] == "C1", "row_status"].iloc[0] == "valid"
    assert gold.loc[gold["customer_id"] == "C2", "row_status"].iloc[0] == "needs_review"
    assert any(i["record_id"] == "C2" and i["issue_type"] == "missing_mandatory_field" for i in issues)


def test_negative_numeric_value_flags_invalid():
    df = pd.DataFrame(
        {
            "product_id": ["P1"],
            "product_name": ["Widget"],
            "weight": [-5.0],
        }
    )
    gold, issues = validate_dataset(df, "product_master", "run_test")
    assert gold.loc[0, "row_status"] == "invalid"
    assert any(i["issue_type"] == "invalid_numeric_value" for i in issues)


def test_negative_inventory_flags_needs_review_not_invalid():
    df = pd.DataFrame(
        {
            "location_id": ["L1"],
            "product_id": ["P1"],
            "snapshot_date": pd.to_datetime(["2025-01-01"]),
            "quantity_on_hand": [-10.0],
        }
    )
    gold, issues = validate_dataset(df, "inventory_history", "run_test")
    assert gold.loc[0, "row_status"] == "needs_review"
    assert any(i["issue_type"] == "negative_inventory_exception" for i in issues)


def test_latitude_out_of_range_is_invalid():
    df = pd.DataFrame(
        {
            "customer_id": ["C1"],
            "customer_name": ["Acme"],
            "city": ["Chicago"],
            "state": ["IL"],
            "postal_code": ["60601"],
            "country": ["USA"],
            "latitude": [200.0],
            "longitude": [-87.6],
        }
    )
    gold, issues = validate_dataset(df, "customer_master", "run_test")
    assert gold.loc[0, "row_status"] == "invalid"
    assert any(i["issue_type"] == "invalid_range" and i["canonical_field"] == "latitude" for i in issues)


def test_cross_reference_check_flags_invalid_product_reference():
    shipment_gold = pd.DataFrame(
        {
            "shipment_id": ["S1", "S2"],
            "origin_location_id": ["L1", "L1"],
            "destination_location_id": ["CUST1", "CUST1"],
            "product_id": ["P1", "P_UNKNOWN"],
            "row_status": ["valid", "valid"],
            "is_valid": [True, True],
        }
    )
    product_master = pd.DataFrame({"product_id": ["P1"]})
    location_master = pd.DataFrame({"location_id": ["L1"]})
    customer_master = pd.DataFrame({"customer_id": ["CUST1"]})
    vendor_master = pd.DataFrame({"vendor_id": []})

    gold, exceptions = cross_reference_check(
        shipment_gold,
        "shipment_history",
        "run_test",
        {
            "product_master": product_master,
            "location_master": location_master,
            "customer_master": customer_master,
            "vendor_master": vendor_master,
        },
    )
    assert gold.loc[gold["shipment_id"] == "S1", "row_status"].iloc[0] == "valid"
    assert gold.loc[gold["shipment_id"] == "S2", "row_status"].iloc[0] == "invalid"
    assert any(e["record_id"] == "S2" and e["field"] == "product_id" for e in exceptions)


def test_flag_in_scope_products_marks_outbound_products():
    product_gold = pd.DataFrame({"product_id": ["P1", "P2", "P3"]})
    shipment_silver = pd.DataFrame(
        {
            "product_id": ["P1", "P2"],
            "direction": ["Outbound", "Inbound"],
        }
    )
    result = flag_in_scope_products(product_gold, shipment_silver)
    assert result.loc[result["product_id"] == "P1", "in_scope"].iloc[0] is True or bool(result.loc[result["product_id"] == "P1", "in_scope"].iloc[0])
    assert not bool(result.loc[result["product_id"] == "P2", "in_scope"].iloc[0])
    assert not bool(result.loc[result["product_id"] == "P3", "in_scope"].iloc[0])
