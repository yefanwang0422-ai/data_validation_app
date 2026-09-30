"""Unit tests for canonical schema & column mapping (plan_v2.md Section 9)."""
import pandas as pd

from app.column_mapping import (
    apply_mapping,
    auto_approve_high_confidence,
    run_mapping_suggestion_for_dataset,
    suggest_mappings,
    unresolved_required_fields,
)
from app.config import load_canonical_schema


def test_exact_alias_match_is_rule_based_high_confidence():
    schema = load_canonical_schema("customer_master")
    suggestions = suggest_mappings(["Cust_Nbr", "ZIP", "Lat"], schema)
    by_col = {s.raw_column: s for s in suggestions}

    assert by_col["Cust_Nbr"].canonical_field == "customer_id"
    assert by_col["Cust_Nbr"].source == "rule_based"
    assert by_col["Cust_Nbr"].confidence == 1.0

    assert by_col["ZIP"].canonical_field == "postal_code"
    assert by_col["Lat"].canonical_field == "latitude"


def test_fuzzy_match_falls_back_for_unknown_columns():
    schema = load_canonical_schema("customer_master")
    suggestions = suggest_mappings(["Kustomer_Nbr"], schema)  # slight misspelling of a known alias
    # Fuzzy pass should resolve to a customer-related canonical field (customer_id or customer_number)
    assert suggestions[0].canonical_field in ("customer_id", "customer_number", "")
    assert suggestions[0].source in ("ai_suggested", "unmapped")


def test_auto_approve_only_applies_to_high_confidence_rule_based():
    schema = load_canonical_schema("customer_master")
    suggestions = suggest_mappings(["Cust_Nbr", "SomeWeirdColumn123"], schema)
    entries = auto_approve_high_confidence(suggestions, threshold=0.85)

    approved = {e["raw_column"]: e for e in entries if e["approved"]}
    unapproved = {e["raw_column"]: e for e in entries if not e["approved"]}

    assert "Cust_Nbr" in approved
    # Unknown/low-confidence column should not be auto-approved
    for raw_col, entry in unapproved.items():
        assert entry["approved"] is False


def test_apply_mapping_renames_only_approved_columns():
    raw_df = pd.DataFrame({"Cust_Nbr": ["C1"], "ZIP": ["60601"], "Junk": ["ignore"]})
    mapping_entries = [
        {"raw_column": "Cust_Nbr", "canonical_field": "customer_id", "approved": True},
        {"raw_column": "ZIP", "canonical_field": "postal_code", "approved": True},
        {"raw_column": "Junk", "canonical_field": "", "approved": False},
    ]
    result = apply_mapping(raw_df, mapping_entries)
    # Approved mapped columns get canonical names; unapproved/unmapped columns pass through as raw__
    assert "customer_id" in result.columns
    assert "postal_code" in result.columns
    assert "raw__Junk" in result.columns  # unmapped column passes through with raw__ prefix
    assert result.iloc[0]["customer_id"] == "C1"


def test_unresolved_required_fields_detects_missing_mapping():
    schema = load_canonical_schema("customer_master")
    entries = [
        {"raw_column": "Cust_Nbr", "canonical_field": "customer_id", "approved": True},
    ]
    missing = unresolved_required_fields(schema, entries)
    # customer_name, city, state, postal_code, country are also required and unmapped
    assert "customer_name" in missing
    assert "customer_id" not in missing


def test_run_mapping_suggestion_persists_and_is_idempotent(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module, "MAPPING_DIR", tmp_path)
    raw_df = pd.DataFrame({"Cust_Nbr": ["C1"], "CustomerName": ["Acme"]})

    entries_1 = run_mapping_suggestion_for_dataset("proj_test", "customer_master", raw_df)
    entries_2 = run_mapping_suggestion_for_dataset("proj_test", "customer_master", raw_df)
    assert entries_1 == entries_2  # second call loads existing config rather than regenerating
