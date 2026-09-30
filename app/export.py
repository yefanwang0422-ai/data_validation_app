"""
Export & Reporting (plan_v2.md Section 13).

Provides:
- Standard exports (CSV/XLSX) of Gold datasets, issue log, review queue, exceptions
- Optilogic/Cosmic Frog-ready export using canonical -> Optilogic field mapping
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.config import EXPORT_DIR, load_canonical_schema
from app.pipeline import load_gold
from app.validation_views import load_issue_log, load_review_queue, load_xref_exceptions


def _export_dir(project_id: str, run_id: str) -> Path:
    p = EXPORT_DIR / project_id / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def export_gold_csv(project_id: str, dataset: str, run_id: str) -> Path:
    df = load_gold(project_id, dataset, run_id)
    out = _export_dir(project_id, run_id) / f"{dataset}_gold.csv"
    df.to_csv(out, index=False)
    return out


def export_gold_xlsx(project_id: str, dataset: str, run_id: str) -> Path:
    df = load_gold(project_id, dataset, run_id)
    out = _export_dir(project_id, run_id) / f"{dataset}_gold.xlsx"
    df.to_excel(out, index=False)
    return out


def export_issue_log(project_id: str, run_id: str) -> Path:
    df = load_issue_log(project_id, run_id)
    out = _export_dir(project_id, run_id) / "issue_log.csv"
    df.to_csv(out, index=False)
    return out


def export_review_queue(project_id: str, run_id: str) -> Path:
    df = load_review_queue(project_id, run_id)
    out = _export_dir(project_id, run_id) / "manual_review_queue.csv"
    df.to_csv(out, index=False)
    return out


def export_cross_reference_exceptions(project_id: str, run_id: str) -> Path:
    df = load_xref_exceptions(project_id, run_id)
    out = _export_dir(project_id, run_id) / "cross_reference_exceptions.csv"
    df.to_csv(out, index=False)
    return out


def export_optilogic_ready(project_id: str, dataset: str, run_id: str) -> Path:
    """
    Reshape/rename Gold data per the canonical -> Optilogic field mapping
    (plan_v2.md Sections 9 & 13), producing an import-ready CSV.
    """
    schema = load_canonical_schema(dataset)
    optilogic_map = schema.to_optilogic_map()

    df = load_gold(project_id, dataset, run_id)
    cols_to_export = [c for c in optilogic_map if c in df.columns]
    optilogic_df = df[cols_to_export].rename(columns=optilogic_map)

    out = _export_dir(project_id, run_id) / f"{dataset}_optilogic.csv"
    optilogic_df.to_csv(out, index=False)
    return out


def export_all(project_id: str, run_id: str, datasets: list) -> dict:
    """Convenience: export everything for a run. Returns dict of output paths."""
    outputs = {}
    for dataset in datasets:
        outputs[f"{dataset}_gold_csv"] = str(export_gold_csv(project_id, dataset, run_id))
        outputs[f"{dataset}_optilogic_csv"] = str(export_optilogic_ready(project_id, dataset, run_id))
    outputs["issue_log"] = str(export_issue_log(project_id, run_id))
    outputs["review_queue"] = str(export_review_queue(project_id, run_id))
    outputs["cross_reference_exceptions"] = str(export_cross_reference_exceptions(project_id, run_id))
    return outputs
