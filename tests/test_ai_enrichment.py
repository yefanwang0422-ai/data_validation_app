"""Unit tests for the AI enrichment engine (plan_v2.md Section 6)."""
import pandas as pd

from app.ai_enrichment import enrich_missing_geo_fields


def test_enrichment_fills_missing_city_from_matching_postal_code():
    df = pd.DataFrame(
        {
            "customer_id": ["C1", "C2"],
            "postal_code": ["60601", "60601"],
            "city": ["Chicago", None],
            "state": ["IL", None],
            "latitude": [41.8, None],
            "longitude": [-87.6, None],
            "row_status": ["valid", "valid"],
            "needs_review": [False, False],
        }
    )
    enriched, review_items = enrich_missing_geo_fields(df, "customer_master", "run_test")

    c2 = enriched[enriched["customer_id"] == "C2"].iloc[0]
    assert c2["city"] == "Chicago"
    assert c2["state"] == "IL"
    assert c2["row_status"] == "needs_review"

    # Every attempted fill must produce a manual review item, regardless of confidence
    assert any(r["record_id"] == "C2" and r["field"] == "city" for r in review_items)
    assert all(r["manual_review_required"] is True for r in review_items)


def test_enrichment_leaves_value_blank_when_no_evidence():
    df = pd.DataFrame(
        {
            "customer_id": ["C1"],
            "postal_code": [None],
            "city": [None],
            "state": [None],
            "latitude": [None],
            "longitude": [None],
            "row_status": ["valid"],
            "needs_review": [False],
        }
    )
    enriched, review_items = enrich_missing_geo_fields(df, "customer_master", "run_test")
    # With no postal_code, city, state, or address, no geocoding is possible.
    # City should remain blank, row_status should stay "valid" (no fill applied).
    city_val = enriched.loc[0, "city"]
    assert pd.isna(city_val) or city_val is None or str(city_val).strip() in ("", "nan", "None")
    # row_status: stays "valid" since nothing was applied (no evidence at all)
    assert enriched.loc[0, "row_status"] == "valid"


def test_enrichment_never_touches_records_with_no_missing_fields():
    df = pd.DataFrame(
        {
            "customer_id": ["C1"],
            "postal_code": ["60601"],
            "city": ["Chicago"],
            "state": ["IL"],
            "latitude": [41.8],
            "longitude": [-87.6],
            "row_status": ["valid"],
            "needs_review": [False],
        }
    )
    enriched, review_items = enrich_missing_geo_fields(df, "customer_master", "run_test")
    assert enriched.loc[0, "row_status"] == "valid"
    assert review_items == []
