"""
Synthetic sample-data generator.

Since no live SQL Server is available in this environment, this module
generates realistic sample raw data (with intentionally *different* column
names than the canonical schema, and some intentional data-quality issues)
to exercise the full pipeline end-to-end: extraction -> mapping -> Silver ->
profiling -> validation -> cross-reference -> AI enrichment -> Gold -> views.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

N_CUSTOMERS = 40
N_LOCATIONS = 12
N_VENDORS = 10
N_PRODUCTS = 25
N_SHIPMENTS = 600
N_PRODUCTION = 300
N_INVENTORY = 400

US_CITIES = [
    ("Chicago", "IL", "60601"),
    ("Dallas", "TX", "75201"),
    ("Atlanta", "GA", "30301"),
    ("Columbus", "OH", "43215"),
    ("Memphis", "TN", "38103"),
    ("Denver", "CO", "80202"),
    ("Phoenix", "AZ", "85001"),
    ("Newark", "NJ", "07102"),
    ("Sacramento", "CA", "95814"),
    ("Charlotte", "NC", "28202"),
    ("", "", ""),  # intentional missing-city case for AI enrichment
]


def _rand_city():
    return random.choice(US_CITIES)


def generate_customer_master() -> pd.DataFrame:
    rows = []
    for i in range(1, N_CUSTOMERS + 1):
        city, state, zip_ = _rand_city()
        rows.append(
            {
                "Cust_Nbr": f"CUST-{i:04d}",
                "CustomerName": f"Customer {i}",
                "City_Raw": city,
                "ST": state,
                "ZIP": zip_,
                "Ctry": "USA",
                "Lat": round(random.uniform(25.0, 48.0), 4) if city else None,
                "Lon": round(random.uniform(-124.0, -70.0), 4) if city else None,
            }
        )
    return pd.DataFrame(rows)


def generate_location_master() -> pd.DataFrame:
    rows = []
    types = ["Plant", "DC", "Port"]
    for i in range(1, N_LOCATIONS + 1):
        city, state, zip_ = _rand_city()
        rows.append(
            {
                "LocID": f"LOC-{i:03d}",
                "LocName": f"Facility {i}",
                "FacType": random.choice(types),
                "City_Raw": city,
                "ST": state,
                "ZIP": zip_,
                "Ctry": "USA",
                "Lat": round(random.uniform(25.0, 48.0), 4) if city else None,
                "Lon": round(random.uniform(-124.0, -70.0), 4) if city else None,
            }
        )
    return pd.DataFrame(rows)


def generate_vendor_master() -> pd.DataFrame:
    rows = []
    for i in range(1, N_VENDORS + 1):
        city, state, zip_ = _rand_city()
        rows.append(
            {
                "VendNbr": f"VEND-{i:03d}",
                "VendorName": f"Vendor {i}",
                "City_Raw": city,
                "ST": state,
                "ZIP": zip_,
                "Ctry": "USA",
                "Lat": round(random.uniform(25.0, 48.0), 4) if city else None,
                "Lon": round(random.uniform(-124.0, -70.0), 4) if city else None,
            }
        )
    return pd.DataFrame(rows)


def generate_product_master() -> pd.DataFrame:
    rows = []
    categories = ["Electronics", "Grocery", "Apparel", "Industrial"]
    for i in range(1, N_PRODUCTS + 1):
        rows.append(
            {
                "SKU": f"SKU-{i:05d}",
                "Descr": f"Product {i}",
                "Cat": random.choice(categories),
                "WeightLbs": round(random.uniform(0.5, 80.0), 2),
                "WeightUOM": "LB",
                "L_in": round(random.uniform(4, 48), 1),
                "W_in": round(random.uniform(4, 48), 1),
                "H_in": round(random.uniform(4, 48), 1),
                "UnitsPerPallet": random.choice([24, 48, 60, 96, None]),
            }
        )
    return pd.DataFrame(rows)


def _rand_date(days_back=365):
    return (datetime(2025, 1, 1) + timedelta(days=random.randint(0, days_back))).date()


def generate_shipment_history(location_ids, customer_ids, vendor_ids, product_ids) -> pd.DataFrame:
    rows = []
    modes = ["Truck", "Rail", "Air", "Ocean"]
    for i in range(1, N_SHIPMENTS + 1):
        is_outbound = random.random() > 0.3
        origin = random.choice(location_ids)
        dest = random.choice(customer_ids) if is_outbound else random.choice(vendor_ids)
        product = random.choice(product_ids + [None]) if random.random() < 0.02 else random.choice(product_ids)
        rows.append(
            {
                "ShipmentNbr": f"SHP-{i:06d}",
                "OriginLoc": origin,
                "ShipToLoc": dest,
                "Item": product,
                "ShipDate": _rand_date(),
                "Qty": round(random.uniform(1, 5000), 1) if random.random() > 0.01 else -5,
                "QtyUOM": "EA",
                "Mode": random.choice(modes),
                "Direction": "Outbound" if is_outbound else "Inbound",
            }
        )
    return pd.DataFrame(rows)


def generate_production_history(location_ids, product_ids) -> pd.DataFrame:
    rows = []
    for i in range(1, N_PRODUCTION + 1):
        rows.append(
            {
                "ProdRecID": f"PROD-{i:06d}",
                "PlantLoc": random.choice(location_ids),
                "Item": random.choice(product_ids),
                "ProdDate": _rand_date(),
                "QtyProduced": round(random.uniform(100, 10000), 1),
                "QtyUOM": "EA",
            }
        )
    return pd.DataFrame(rows)


def generate_shipment_cost(shipment_ids, vendor_ids) -> pd.DataFrame:
    rows = []
    cost_types = ["Freight", "FuelSurcharge", "Handling"]
    sample_shipments = random.sample(shipment_ids, min(len(shipment_ids), 500))
    for i, ship_id in enumerate(sample_shipments, start=1):
        rows.append(
            {
                "ShipmentNbr": ship_id,
                "Amount": round(random.uniform(50, 5000), 2),
                "Curr": "USD",
                "CostType": random.choice(cost_types),
                "CarrierVendor": random.choice(vendor_ids),
            }
        )
    return pd.DataFrame(rows)


def generate_inventory_history(location_ids, product_ids) -> pd.DataFrame:
    rows = []
    for i in range(1, N_INVENTORY + 1):
        rows.append(
            {
                "LocID": random.choice(location_ids),
                "Item": random.choice(product_ids),
                "SnapDate": _rand_date(),
                "OnHandQty": round(random.uniform(0, 20000), 1) if random.random() > 0.01 else -10,
                "QtyUOM": "EA",
            }
        )
    return pd.DataFrame(rows)


def generate_all_sample_data() -> dict:
    customer_df = generate_customer_master()
    location_df = generate_location_master()
    vendor_df = generate_vendor_master()
    product_df = generate_product_master()

    location_ids = location_df["LocID"].tolist()
    customer_ids = customer_df["Cust_Nbr"].tolist()
    vendor_ids = vendor_df["VendNbr"].tolist()
    product_ids = product_df["SKU"].tolist()

    shipment_df = generate_shipment_history(location_ids, customer_ids, vendor_ids, product_ids)
    production_df = generate_production_history(location_ids, product_ids)
    shipment_cost_df = generate_shipment_cost(shipment_df["ShipmentNbr"].tolist(), vendor_ids)
    inventory_df = generate_inventory_history(location_ids, product_ids)

    # Split shipment_history into inbound and outbound for the new separate datasets
    direction_col = "Direction"
    inbound_df = shipment_df[shipment_df[direction_col] == "Inbound"].reset_index(drop=True)
    outbound_df = shipment_df[shipment_df[direction_col] == "Outbound"].reset_index(drop=True)

    return {
        "customer_master": customer_df,
        "location_master": location_df,
        "vendor_master": vendor_df,
        "product_master": product_df,
        "shipment_history": shipment_df,
        "inbound_shipment_history": inbound_df,
        "outbound_shipment_history": outbound_df,
        "production_history": production_df,
        "shipment_cost": shipment_cost_df,
        "inventory_history": inventory_df,
    }
