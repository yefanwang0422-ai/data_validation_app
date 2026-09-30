"""
Streamlit MVP frontend (plan_v2.md Section 8 / Section 16).

Screens:
1. Extraction / run trigger
2. Run status & history
3. Profiling report viewer
4. Dataset quality dashboard
5. Issue explorer
6. Cross-reference exception viewer
7. AI-fill review queue
8. Record detail view (raw vs validated)
9. Column mapping review screen
10. Business Insights (with persistent Validated/All/Flagged filter)
11. Export/download page
"""
from __future__ import annotations

import json

import streamlit as st

from app.business_metrics import METRIC_REGISTRY
from app.config import DATASETS, MAPPING_DIR, RUN_LOG_DIR
from app.export import export_all, export_optilogic_ready
from app.pipeline import load_gold, run_full_pipeline
from app.validation_views import (
    get_ai_fill_review,
    get_cross_reference_exceptions,
    get_dataset_quality_summary,
    get_issue_flagged,
    get_raw_vs_validated,
    load_run_summary,
)

st.set_page_config(page_title="Network Design Data Prep", layout="wide")

DEFAULT_PROJECT = "demo_project"

if "project_id" not in st.session_state:
    st.session_state.project_id = DEFAULT_PROJECT
if "run_id" not in st.session_state:
    st.session_state.run_id = None

st.sidebar.title("Network Design Data Prep")
st.session_state.project_id = st.sidebar.text_input("Project ID", st.session_state.project_id)

screen = st.sidebar.radio(
    "Screen",
    [
        "1. Run Extraction / Pipeline",
        "2. Run Status & History",
        "3. Profiling Report",
        "4. Dataset Quality Dashboard",
        "5. Issue Explorer",
        "6. Cross-Reference Exceptions",
        "7. AI-Fill Review Queue",
        "8. Record Detail (Raw vs Validated)",
        "9. Column Mapping Review",
        "10. Business Insights",
        "11. Export / Download",
    ],
)

project_id = st.session_state.project_id


def _run_id_picker():
    run_log_dir = RUN_LOG_DIR / project_id
    if not run_log_dir.exists():
        st.warning("No runs found for this project yet. Trigger a run first.")
        return None
    summaries = sorted(run_log_dir.glob("*_summary.json"))
    if not summaries:
        st.warning("No completed runs found.")
        return None
    run_ids = [p.name.replace("_summary.json", "") for p in summaries]
    run_ids.sort(reverse=True)
    return st.selectbox("Select Run", run_ids)


# ---------------------------------------------------------------------------
# Screen 1: Run Extraction / Pipeline
# ---------------------------------------------------------------------------
if screen.startswith("1."):
    st.header("Run Extraction / Pipeline")
    st.write(
        "Runs the full pipeline: SQL/sample extraction -> Bronze -> canonical mapping -> "
        "Silver -> profiling -> validation -> cross-reference -> AI enrichment -> Gold."
    )
    st.info("No live SQL Server configured in this environment; using synthetic sample data "
            "that mimics a real ERP/WMS export with different raw column names.")
    if st.button("Run Full Pipeline Now", type="primary"):
        with st.spinner("Running pipeline across all 8 datasets..."):
            summary = run_full_pipeline(project_id, use_sample_data=True)
        st.session_state.run_id = summary["run_id"]
        st.success(f"Run complete: {summary['run_id']}")
        st.json(summary)

# ---------------------------------------------------------------------------
# Screen 2: Run Status & History
# ---------------------------------------------------------------------------
elif screen.startswith("2."):
    st.header("Run Status & History")
    run_id = _run_id_picker()
    if run_id:
        summary = load_run_summary(project_id, run_id)
        st.json(summary)

# ---------------------------------------------------------------------------
# Screen 3: Profiling Report
# ---------------------------------------------------------------------------
elif screen.startswith("3."):
    st.header("Profiling Report")
    run_id = _run_id_picker()
    dataset = st.selectbox("Dataset", DATASETS)
    if run_id:
        profile_path = RUN_LOG_DIR / project_id / "profiles" / dataset / f"{run_id}.json"
        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
            st.subheader("Schema Drift vs Previous Run")
            st.json(report["schema_drift"])
            st.subheader("Column Profile")
            st.dataframe(report["profile"]["columns"])
        else:
            st.warning("No profiling report found for this dataset/run.")

# ---------------------------------------------------------------------------
# Screen 4: Dataset Quality Dashboard
# ---------------------------------------------------------------------------
elif screen.startswith("4."):
    st.header("Dataset Quality Dashboard")
    run_id = _run_id_picker()
    if run_id:
        cols = st.columns(4)
        for i, dataset in enumerate(DATASETS):
            summary = get_dataset_quality_summary(project_id, dataset, run_id)
            with cols[i % 4]:
                st.metric(dataset, f"{summary.get('pct_valid', 0)}% valid", f"{summary.get('row_count', 0)} rows")
                st.caption(
                    f"Review: {summary.get('pct_needs_review', 0)}% | "
                    f"Invalid: {summary.get('pct_invalid', 0)}% | "
                    f"AI-filled: {summary.get('ai_filled_count', 0)}"
                )

# ---------------------------------------------------------------------------
# Screen 5: Issue Explorer
# ---------------------------------------------------------------------------
elif screen.startswith("5."):
    st.header("Issue Explorer")
    run_id = _run_id_picker()
    dataset = st.selectbox("Dataset", DATASETS)
    if run_id:
        df = get_issue_flagged(project_id, dataset, run_id)
        st.write(f"{len(df)} issues found for {dataset}.")
        st.dataframe(df)

# ---------------------------------------------------------------------------
# Screen 6: Cross-Reference Exceptions
# ---------------------------------------------------------------------------
elif screen.startswith("6."):
    st.header("Cross-Reference Exceptions")
    run_id = _run_id_picker()
    dataset = st.selectbox("Dataset", DATASETS)
    if run_id:
        df = get_cross_reference_exceptions(project_id, dataset, run_id)
        st.write(f"{len(df)} cross-reference exceptions found for {dataset}.")
        st.dataframe(df)

# ---------------------------------------------------------------------------
# Screen 7: AI-Fill Review Queue
# ---------------------------------------------------------------------------
elif screen.startswith("7."):
    st.header("AI-Fill Review Queue")
    run_id = _run_id_picker()
    dataset = st.selectbox("Dataset", DATASETS)
    if run_id:
        df = get_ai_fill_review(project_id, dataset, run_id)
        st.write(f"{len(df)} AI-assisted fill candidates for {dataset}.")
        st.dataframe(df)
        st.caption("All AI-filled values require manual approval before being treated as confirmed.")

# ---------------------------------------------------------------------------
# Screen 8: Record Detail (Raw vs Validated)
# ---------------------------------------------------------------------------
elif screen.startswith("8."):
    st.header("Record Detail (Raw vs Validated)")
    run_id = _run_id_picker()
    dataset = st.selectbox("Dataset", DATASETS)
    status_filter = st.radio("Filter", ["all", "validated", "flagged"], horizontal=True)
    if run_id:
        df = get_raw_vs_validated(project_id, dataset, run_id, status_filter=status_filter)
        st.write(f"{len(df)} records ({status_filter}).")
        st.dataframe(df)

# ---------------------------------------------------------------------------
# Screen 9: Column Mapping Review
# ---------------------------------------------------------------------------
elif screen.startswith("9."):
    st.header("Column Mapping Review")
    dataset = st.selectbox("Dataset", DATASETS)
    mapping_path = MAPPING_DIR / project_id / f"{dataset}.json"
    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        st.dataframe(entries)
        st.caption(
            "Approved mappings drive Silver/Gold canonical renaming. "
            "AI-suggested (fuzzy-match) mappings below the auto-approve threshold require manual approval."
        )
    else:
        st.info("No mapping config found yet for this dataset. Run the pipeline once to auto-onboard.")

# ---------------------------------------------------------------------------
# Screen 10: Business Insights
# ---------------------------------------------------------------------------
elif screen.startswith("10."):
    st.header("Business Insights")
    run_id = _run_id_picker()
    status_filter = st.radio(
        "Validated Filter (applies to all charts below)",
        ["all", "validated", "flagged"],
        horizontal=True,
    )
    if run_id:
        for metric_name, fn in METRIC_REGISTRY.items():
            st.subheader(metric_name.replace("_", " ").title())
            fig = fn(project_id, run_id, status_filter=status_filter)
            st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Screen 11: Export / Download
# ---------------------------------------------------------------------------
elif screen.startswith("11."):
    st.header("Export / Download")
    run_id = _run_id_picker()
    if run_id:
        if st.button("Generate All Exports (Gold CSV + Optilogic-ready + Logs)"):
            outputs = export_all(project_id, run_id, DATASETS)
            st.success("Exports generated:")
            st.json(outputs)

        dataset = st.selectbox("Or export a single dataset in Optilogic-ready format", DATASETS)
        if st.button("Export Optilogic-Ready CSV"):
            path = export_optilogic_ready(project_id, dataset, run_id)
            st.success(f"Exported to: {path}")
