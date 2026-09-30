"""
Core configuration, path, and canonical-schema loading utilities.

This module is the single place that knows about:
- project directory layout (bronze/silver/gold/configs)
- run_id generation
- loading canonical schema definitions (Section 9 of plan_v2.md)
- loading / saving per-project column mapping metadata
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "configs"
CANONICAL_SCHEMA_DIR = CONFIG_DIR / "canonical_schema"
MAPPING_DIR = CONFIG_DIR / "column_mappings"
DATA_SOURCE_REGISTRY_DIR = CONFIG_DIR / "data_sources"
DATA_DIR = ROOT_DIR / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
EXPORT_DIR = DATA_DIR / "exports"
RUN_LOG_DIR = DATA_DIR / "run_logs"
UPLOAD_DIR = DATA_DIR / "uploads"

DATASETS = [
    "customer_master",
    "location_master",
    "vendor_master",
    "product_master",
    "production_history",
    "shipment_history",
    "inbound_shipment_history",
    "outbound_shipment_history",
    "shipment_cost",
    "inventory_history",
]

MASTER_DATASETS = [
    "customer_master",
    "location_master",
    "vendor_master",
    "product_master",
]

TRANSACTIONAL_DATASETS = [
    "production_history",
    "shipment_history",
    "inbound_shipment_history",
    "outbound_shipment_history",
    "shipment_cost",
    "inventory_history",
]

for _dir in (MAPPING_DIR, BRONZE_DIR, SILVER_DIR, GOLD_DIR, EXPORT_DIR, RUN_LOG_DIR, DATA_SOURCE_REGISTRY_DIR, UPLOAD_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def new_run_id() -> str:
    """Generate a versioned, sortable run id."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"run_{ts}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Canonical schema
# ---------------------------------------------------------------------------

@dataclass
class CanonicalField:
    name: str
    type: str
    required: bool
    description: str = ""
    optilogic_field: Optional[str] = None


@dataclass
class CanonicalSchema:
    dataset: str
    fields: List[CanonicalField] = field(default_factory=list)

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]

    @property
    def required_field_names(self) -> List[str]:
        return [f.name for f in self.fields if f.required]

    def to_optilogic_map(self) -> Dict[str, str]:
        return {f.name: f.optilogic_field for f in self.fields if f.optilogic_field}


_CANONICAL_CACHE: Dict[str, CanonicalSchema] = {}


def load_canonical_schema(dataset: str) -> CanonicalSchema:
    """Load (and cache) the canonical schema config for a dataset."""
    if dataset in _CANONICAL_CACHE:
        return _CANONICAL_CACHE[dataset]

    path = CANONICAL_SCHEMA_DIR / f"{dataset}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No canonical schema defined for dataset '{dataset}' at {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    fields = [
        CanonicalField(
            name=f["name"],
            type=f.get("type", "string"),
            required=bool(f.get("required", False)),
            description=f.get("description", ""),
            optilogic_field=f.get("optilogic_field"),
        )
        for f in raw.get("canonical_fields", [])
    ]
    schema = CanonicalSchema(dataset=raw["dataset"], fields=fields)
    _CANONICAL_CACHE[dataset] = schema
    return schema


def load_all_canonical_schemas() -> Dict[str, CanonicalSchema]:
    return {ds: load_canonical_schema(ds) for ds in DATASETS}


# ---------------------------------------------------------------------------
# Per-project column mapping metadata (Section 9)
# ---------------------------------------------------------------------------

def mapping_config_path(project_id: str, dataset: str) -> Path:
    proj_dir = MAPPING_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir / f"{dataset}.json"


def load_mapping_config(project_id: str, dataset: str) -> List[Dict[str, Any]]:
    """
    Returns a list of mapping entries:
      { raw_column, canonical_field, confidence, source, approved, approver, timestamp }
    """
    path = mapping_config_path(project_id, dataset)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_mapping_config(project_id: str, dataset: str, entries: List[Dict[str, Any]]) -> None:
    path = mapping_config_path(project_id, dataset)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, default=str)


def approved_mapping_dict(project_id: str, dataset: str) -> Dict[str, str]:
    """raw_column -> canonical_field, approved entries only."""
    entries = load_mapping_config(project_id, dataset)
    return {e["raw_column"]: e["canonical_field"] for e in entries if e.get("approved")}


# ---------------------------------------------------------------------------
# Per-project data source registry (SQL / file / none per dataset)
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_TYPE = "none"  # "sql" | "file" | "none"


def data_source_registry_path(project_id: str) -> Path:
    return DATA_SOURCE_REGISTRY_DIR / f"{project_id}.json"


def load_data_source_registry(project_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns: { dataset: { "source_type": "sql"|"file"|"none", "upload_filename": str|None } }
    Defaults every dataset to "none" if not yet configured.
    """
    path = data_source_registry_path(project_id)
    registry: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            registry = json.load(fh)
    for ds in DATASETS:
        if ds not in registry:
            registry[ds] = {"source_type": DEFAULT_SOURCE_TYPE, "upload_filename": None}
    return registry


def save_data_source_registry(project_id: str, registry: Dict[str, Dict[str, Any]]) -> None:
    path = data_source_registry_path(project_id)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, default=str)


def set_dataset_source_type(project_id: str, dataset: str, source_type: str) -> None:
    registry = load_data_source_registry(project_id)
    registry[dataset]["source_type"] = source_type
    save_data_source_registry(project_id, registry)


def upload_dir_for(project_id: str) -> Path:
    p = UPLOAD_DIR / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p
