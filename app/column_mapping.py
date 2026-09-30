"""
Canonical Schema & Column Mapping (plan_v2.md Section 9).

Provides:
- rule-based / fuzzy-match mapping suggestion utility
- mapping approval helpers
- application of an approved mapping to rename a raw DataFrame into canonical
  field names (used by the Silver ETL step)

AI-assisted mapping is represented here by the fuzzy-match suggestion engine,
which stands in for an LLM-backed suggestion in environments without network/LLM
access. The same interface (raw_column -> canonical_field, confidence, rationale)
is preserved so a real LLM call can be swapped in later without changing callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
from rapidfuzz import fuzz

from app.config import CanonicalSchema, load_canonical_schema, load_mapping_config, save_mapping_config

# Common aliases seen across ERP/WMS/TMS systems -> canonical field.
# This is the "rule-based first pass" described in plan_v2.md Section 9.
ALIAS_HINTS: Dict[str, List[str]] = {
    # ---- Identifiers ----
    "customer_id": ["cust_nbr", "custid", "customerid", "cust_id", "customer_no", "custno", "cust_number", "acct_no"],
    "customer_name": ["customername", "custname", "cust_name", "name", "customer", "acctname"],
    "customer_number": ["cust_number", "cust_acct", "account_no", "acctno"],
    "account_type": ["acct_type", "accounttype", "customer_type", "custtype"],
    "customer_status": ["cust_status", "status", "active"],
    "location_id": ["locid", "loc_id", "facilityid", "plantid", "plant_loc", "originloc", "whseid", "site_id", "dc_id"],
    "location_name": ["locname", "facilityname", "facility_name", "plantname", "warehouse_name", "site_name"],
    "location_type": ["factype", "facility_type", "loctype", "site_type", "node_type"],
    "location_status": ["loc_status", "facility_status"],
    "company_code": ["company", "plant_code", "business_unit", "bu_code", "entity_code"],
    "vendor_id": ["vendnbr", "vendorid", "vendor_no", "carriervendor", "suppid", "supplier_id", "carrier_id", "carrierid"],
    "vendor_name": ["vendorname", "vendname", "vendor", "supplier_name", "suppname", "carriername", "carrier_name"],
    "vendor_number": ["vend_no", "supp_no", "supplier_no"],
    "vendor_type": ["vend_type", "supplier_type"],
    "vendor_status": ["vend_status", "supplier_status"],
    "carrier_id": ["carrierid", "carrier_no", "scac"],
    "carrier_name": ["carriername", "carrier"],
    "product_id": ["sku", "item", "productid", "product_no", "itemnbr", "item_no", "material", "materialid", "article"],
    "product_name": ["descr", "description", "productname", "itemdescr", "item_desc", "item_description", "product_desc"],
    "product_category": ["cat", "category", "productcategory", "family", "prod_cat", "item_cat", "commodity"],
    "product_family": ["prod_family", "item_family", "product_group2"],
    "product_group": ["prod_group", "item_group", "planning_group"],
    "brand": ["brand_name", "brand_code"],
    "upc": ["barcode", "ean", "gtin"],
    "product_status": ["item_status", "sku_status", "material_status", "active_flag"],
    # ---- Address ----
    "address_line_1": ["address", "addr1", "addr_1", "street", "street1", "street_address"],
    "address_line_2": ["addr2", "addr_2", "street2", "suite", "unit"],
    "city": ["city_raw", "city", "shipcity", "destregioncity"],
    "state": ["st", "state", "province", "statecode", "state_cd", "state_prov"],
    "postal_code": ["zip", "zipcode", "postalcode", "postal_code", "zip_code", "postcode"],
    "country": ["ctry", "country", "countrycode", "country_code", "country_cd"],
    "region": ["sales_region", "territory", "distribution_region", "area"],
    "latitude": ["lat", "latitude", "geo_lat"],
    "longitude": ["lon", "lng", "longitude", "geo_lon"],
    # ---- Contact ----
    "contact_name": ["contact", "primary_contact", "rep_name"],
    "phone": ["telephone", "tel", "phone_no", "phone_number"],
    "email": ["email_address", "email_addr"],
    # ---- Product dimensions ----
    "weight": ["weightlbs", "weight_lbs", "unitweight", "unit_weight", "gross_weight"],
    "weight_uom": ["weightuom", "weight_unit", "wt_uom"],
    "length": ["l_in", "length_in", "unit_length", "dim_length"],
    "width": ["w_in", "width_in", "unit_width", "dim_width"],
    "height": ["h_in", "height_in", "unit_height", "dim_height"],
    "dimension_uom": ["dim_uom", "dimensions_uom", "size_uom"],
    "units_per_case": ["units_per_cs", "units_case", "pack_size", "inner_pack"],
    "cases_per_pallet": ["cases_pallet", "cs_per_pallet"],
    "units_per_pallet": ["unitsperpallet", "pallet_qty", "palletconversion", "units_per_plt"],
    "freight_class": ["freight_cls", "nmfc_class", "ltl_class", "freight_classification"],
    "hazmat_flag": ["hazmat", "hazardous", "dangerous_goods"],
    "temperature_class": ["temp_class", "temp_req", "temperature_requirement", "cold_chain"],
    "storage_class": ["storage_type", "commodity_class", "handling_class"],
    "abc_class": ["abc", "velocity_class", "pareto_class"],
    "lead_time_days": ["lead_time", "lt_days", "order_lead_time"],
    "shelf_life_days": ["shelf_life", "expiry_days"],
    "unit_cost": ["std_cost", "standard_cost", "cost_per_unit"],
    "unit_price": ["list_price", "sell_price", "price"],
    # ---- Shipment ----
    "shipment_id": ["shipmentnbr", "shipment_no", "shipmentid", "bol", "pro_number", "pronum"],
    "order_id": ["order_no", "orderno", "po_number", "ponbr", "so_number", "sales_order"],
    "lane_id": ["lane", "lane_code", "od_pair"],
    "origin_location_id": ["originloc", "origin_location", "shipfromloc", "origin", "source", "shipper_loc"],
    "origin_location_name": ["origin_name", "shipper_name", "origin_loc_name"],
    "origin_city": ["orig_city", "from_city", "origin_city", "ship_from_city"],
    "origin_state": ["orig_state", "from_state", "origin_state"],
    "origin_postal_code": ["orig_zip", "from_zip", "origin_zip"],
    "origin_country": ["orig_country", "from_country"],
    "destination_location_id": ["shiptoloc", "destinationloc", "ship_to_loc", "dest", "destination", "consignee_loc"],
    "destination_location_name": ["dest_name", "consignee_name", "destination_name"],
    "destination_city": ["dest_city", "to_city", "ship_to_city"],
    "destination_state": ["dest_state", "to_state"],
    "destination_postal_code": ["dest_zip", "to_zip", "ship_to_zip"],
    "destination_country": ["dest_country", "to_country"],
    "shipment_date": ["shipdate", "ship_date", "actual_ship_date", "departure_date"],
    "delivery_date": ["actual_delivery", "delivery_dt", "arrival_date", "pod_date"],
    "promised_date": ["req_delivery", "required_delivery", "commit_date", "promise_date"],
    "order_date": ["order_dt", "placed_date", "po_date"],
    "volume": ["qty", "quantity", "volume", "shipped_qty", "order_qty"],
    "volume_uom": ["qtyuom", "quantityuom", "qty_uom", "unit"],
    "weight_shipped": ["shipped_weight", "gross_wt", "total_weight"],
    "pallet_count": ["pallet_qty", "num_pallets", "pallets"],
    "shipment_mode": ["mode", "transportmode", "shipmode", "trans_mode", "freight_mode"],
    "service_level": ["service", "service_type", "delivery_type", "freight_service"],
    "tracking_number": ["tracking", "bol_number", "pro_nbr", "tracking_no"],
    "direction": ["direction", "flow", "shipment_direction", "inbound_outbound"],
    # ---- Production ----
    "production_id": ["prodrecid", "prod_id", "production_record_id"],
    "work_order_id": ["work_order", "wo_number", "manufacturing_order", "mo_number"],
    "batch_id": ["batch", "lot_id", "batch_no", "lot"],
    "start_date": ["start_dt", "prod_start", "production_start"],
    "end_date": ["end_dt", "prod_end", "production_end", "completion_date"],
    "production_date": ["proddate", "prod_date", "production_date", "mfg_date"],
    "quantity_produced": ["qtyproduced", "quantity_produced", "actual_qty", "produced_qty"],
    "planned_quantity": ["plan_qty", "planned_qty", "scheduled_qty"],
    "reject_quantity": ["reject_qty", "scrap_qty", "defect_qty"],
    "yield_quantity": ["yield_qty", "good_qty", "net_produced"],
    "quantity_uom": ["qtyuom", "qty_uom", "unit", "uom"],
    "line_id": ["prod_line", "production_line", "line", "assembly_line"],
    "shift": ["shift_name", "work_shift"],
    # ---- Shipment cost ----
    "cost_amount": ["amount", "cost", "costamount", "total_cost", "freight_cost", "total_charge"],
    "base_freight_amount": ["base_rate", "linehaul", "freight_charge", "base_charge"],
    "fuel_surcharge_amount": ["fuel_surcharge", "fsc", "fuel_charge"],
    "fuel_surcharge_pct": ["fsc_pct", "fuel_pct", "fsc_percent"],
    "accessorial_amount": ["accessorial", "accessorial_charge", "extra_charge"],
    "discount_amount": ["discount", "rebate", "rate_discount"],
    "currency": ["curr", "currency", "currency_code"],
    "cost_type": ["costtype", "cost_type", "charge_type"],
    "invoice_number": ["invoice_no", "invoice_nbr", "bill_no", "inv_no"],
    "invoice_date": ["invoice_dt", "bill_date", "billing_date"],
    "payment_terms": ["pay_terms", "terms", "net_terms"],
    # ---- Inventory ----
    "snapshot_date": ["snapdate", "snapshot_date", "inventory_date", "as_of_date", "report_date"],
    "quantity_on_hand": ["onhandqty", "quantity_on_hand", "qtyonhand", "on_hand", "stock_qty", "total_on_hand"],
    "quantity_available": ["avail_qty", "available_qty", "qty_available"],
    "quantity_reserved": ["reserved_qty", "committed_qty", "allocated_qty"],
    "quantity_in_transit": ["in_transit_qty", "intransit", "transit_qty"],
    "quantity_on_order": ["on_order_qty", "open_po_qty", "order_qty"],
    "safety_stock": ["ss_qty", "safety_stock_qty", "min_stock"],
    "reorder_point": ["rop", "reorder_qty", "order_point"],
    "max_stock": ["max_qty", "max_inventory", "max_level"],
    "inventory_status": ["stock_status", "inv_status", "hold_reason"],
    "warehouse_id": ["whse_id", "warehouse_code", "whs_code"],
    "zone": ["warehouse_zone", "storage_zone", "pick_zone"],
    "bin": ["bin_no", "bin_location", "slot", "slot_id", "position"],
    "lot_number": ["lot", "lot_no", "lot_nbr", "batch_no"],
    "inventory_record_id": ["inv_rec_id", "inventory_id"],
    # ---- Common date / metadata ----
    "created_date": ["create_date", "create_dt", "creation_date", "add_date"],
    "last_modified_date": ["modified_date", "update_date", "last_update", "modified_dt"],
    # ---- Facility cost / capacity ----
    "storage_capacity": ["capacity", "whse_capacity", "storage_cap"],
    "fixed_cost": ["annual_fixed_cost", "facility_fixed_cost"],
    "variable_cost_per_unit": ["variable_cost", "handling_cost", "unit_handling"],
    # ---- Product pricing ----
    "credit_limit": ["credit", "cust_credit"],
    "segment": ["market_segment", "vertical", "cust_segment"],
}


@dataclass
class MappingSuggestion:
    raw_column: str
    canonical_field: str
    confidence: float
    rationale: str
    source: str  # "rule_based" or "ai_suggested"


def _normalize(s: str) -> str:
    return s.strip().lower().replace(" ", "").replace("-", "_").replace("__", "_")


def suggest_mappings(raw_columns: List[str], schema: CanonicalSchema) -> List[MappingSuggestion]:
    """
    Suggest raw_column -> canonical_field mappings.

    Pass 1: exact alias match (rule_based, confidence 1.0)
    Pass 2: fuzzy string match against canonical field name / aliases (ai_suggested proxy)
    """
    suggestions: List[MappingSuggestion] = []
    used_canonical: set = set()

    # Build normalized alias lookup: normalized_alias -> canonical_field
    alias_lookup: Dict[str, str] = {}
    for canon, aliases in ALIAS_HINTS.items():
        for a in aliases:
            alias_lookup[_normalize(a)] = canon

    for raw_col in raw_columns:
        norm = _normalize(raw_col)

        # Pass 1: exact alias hit
        if norm in alias_lookup and alias_lookup[norm] in schema.field_names:
            canon = alias_lookup[norm]
            if canon not in used_canonical:
                suggestions.append(
                    MappingSuggestion(
                        raw_column=raw_col,
                        canonical_field=canon,
                        confidence=1.0,
                        rationale=f"Exact alias match: '{raw_col}' is a known alias for '{canon}'.",
                        source="rule_based",
                    )
                )
                used_canonical.add(canon)
                continue

        # Pass 2: fuzzy match against canonical field names + their aliases
        best_score = 0.0
        best_field = None
        for field in schema.fields:
            candidates = [field.name] + ALIAS_HINTS.get(field.name, [])
            score = max(fuzz.ratio(norm, _normalize(c)) for c in candidates) / 100.0
            if score > best_score:
                best_score = score
                best_field = field.name

        if best_field and best_field not in used_canonical and best_score >= 0.55:
            suggestions.append(
                MappingSuggestion(
                    raw_column=raw_col,
                    canonical_field=best_field,
                    confidence=round(best_score, 2),
                    rationale=(
                        f"Fuzzy match: '{raw_col}' most closely resembles canonical field "
                        f"'{best_field}' (similarity {best_score:.2f})."
                    ),
                    source="ai_suggested",
                )
            )
            used_canonical.add(best_field)
        else:
            suggestions.append(
                MappingSuggestion(
                    raw_column=raw_col,
                    canonical_field="",
                    confidence=0.0,
                    rationale=f"No confident canonical match found for '{raw_col}'.",
                    source="unmapped",
                )
            )

    return suggestions


def auto_approve_high_confidence(
    suggestions: List[MappingSuggestion], threshold: float = 0.85
) -> List[dict]:
    """
    Convert suggestions into mapping-entry dicts, auto-approving high-confidence
    rule_based hits.

    ALL raw columns are included — even unmapped ones (canonical_field = "").
    This ensures the mapping review always shows every column from the source file
    so the user can decide whether to map it or leave it blank (= excluded/pass-through).
    """
    entries = []
    now = datetime.now(timezone.utc).isoformat()
    for s in suggestions:
        approved = (
            s.source == "rule_based"
            and s.confidence >= threshold
            and bool(s.canonical_field)
        )
        entries.append(
            {
                "raw_column": s.raw_column,
                "canonical_field": s.canonical_field,   # "" = intentionally unmapped / excluded
                "confidence": s.confidence,
                "source": s.source,
                "rationale": s.rationale,
                "approved": approved,
                "approver": "system" if approved else None,
                "timestamp": now,
            }
        )
    return entries


def run_mapping_suggestion_for_dataset(
    project_id: str, dataset: str, raw_df: pd.DataFrame, overwrite: bool = False
) -> List[dict]:
    """
    Suggest mappings for a dataset's raw columns, auto-approve high-confidence
    rule-based matches, and persist to the project's mapping config.

    Behaviour:
    - overwrite=False (default): return existing config unchanged if it already exists.
    - overwrite=True (legacy/forced refresh): generate fresh suggestions from scratch,
      BUT preserve any previously user-approved mappings via smart-merge so that
      approved choices are never discarded on re-extraction (see merge_approved_mappings).
    """
    existing = load_mapping_config(project_id, dataset)
    if existing and not overwrite:
        return existing

    schema = load_canonical_schema(dataset)
    suggestions = suggest_mappings(list(raw_df.columns), schema)
    entries = auto_approve_high_confidence(suggestions)

    if existing:
        # Smart-merge: preserve user-approved choices from previous runs
        entries = merge_approved_mappings(existing, entries)

    save_mapping_config(project_id, dataset, entries)
    return entries


def merge_approved_mappings(
    previous_entries: List[dict], new_entries: List[dict]
) -> List[dict]:
    """
    Merge new mapping suggestions with a previous config, preserving all
    user-approved choices so they survive data re-extractions.

    Rules per raw column:
    - If the column had an APPROVED mapping in the previous config →
      keep the previous entry intact (user's confirmed choice).
    - If the column is new (not in previous config) or was previously
      unapproved → use the new suggestion.
    - Columns that existed previously but are absent from the new extraction
      (column was removed from the data source) are dropped.

    This means:
    - User only needs to approve a column's mapping ONCE per project/dataset.
    - New columns that appear after a re-extraction get fresh AI suggestions.
    - Unapproved/unmapped columns get re-suggested in case the AI improves.
    """
    approved_previous: dict = {
        e["raw_column"]: e
        for e in previous_entries
        if e.get("approved") and e.get("canonical_field")
    }

    merged = []
    for new_entry in new_entries:
        raw_col = new_entry["raw_column"]
        if raw_col in approved_previous:
            # Keep the user's previously confirmed mapping
            merged.append(approved_previous[raw_col])
        else:
            # New column or previously unapproved — use fresh suggestion
            merged.append(new_entry)

    return merged


def apply_mapping(raw_df: pd.DataFrame, mapping_entries: List[dict]) -> pd.DataFrame:
    """
    Rename raw columns to canonical field names using APPROVED mapping entries whose
    raw_column exists in raw_df. Columns with no approved mapping are passed through
    under their original raw names (prefixed with 'raw__') so that ALL data from the
    source file is preserved in Silver -- nothing is silently dropped.

    Stale mapping entries referencing columns not present in the file are ignored.
    """
    # Build rename map from approved entries that exist in the file
    rename_map = {
        e["raw_column"]: e["canonical_field"]
        for e in mapping_entries
        if e.get("approved") and e["raw_column"] in raw_df.columns and e.get("canonical_field")
    }

    if not rename_map:
        # No approved mappings at all -- pass ALL columns through with raw__ prefix
        # so the caller can detect this and regenerate mappings.
        return pd.DataFrame(columns=[])

    canonical_df = raw_df.copy()

    # Rename the mapped columns to their canonical names
    canonical_df = canonical_df.rename(columns=rename_map)

    # For unmapped columns (not in the rename_map values, not already renamed),
    # prefix them with 'raw__' to make clear they are unverified raw columns
    # that were not mapped to a canonical field, but still keep them in Silver.
    mapped_raw_cols = set(rename_map.keys())
    unmapped_cols = [col for col in raw_df.columns if col not in mapped_raw_cols]
    passthrough_rename = {col: f"raw__{col}" for col in unmapped_cols if f"raw__{col}" not in canonical_df.columns}
    canonical_df = canonical_df.rename(columns=passthrough_rename)

    return canonical_df.copy()


def unresolved_required_fields(schema: CanonicalSchema, mapping_entries: List[dict]) -> List[str]:
    """Return required canonical fields that have no approved mapping yet."""
    mapped_canonical = {e["canonical_field"] for e in mapping_entries if e.get("approved")}
    return [f for f in schema.required_field_names if f not in mapped_canonical]
