# Data Pre-Processing for Network Design

A Python-native app that pulls raw supply-chain data, cleans/validates/enriches it,
and produces a modeling-ready, auditable dataset — implemented per `plan_v2.md`.

## What this implements (mapped to `plan_v2.md`)

| Milestone | Section(s) | Module(s) | Status |
|---|---|---|---|
| 1. Extraction & Staging | 0 | `app/extraction.py`, `app/sample_data.py` | Done |
| 2. ETL, Canonical Mapping & Profiling | 1, 2, 9 | `app/silver_etl.py`, `app/column_mapping.py`, `app/profiling.py`, `configs/canonical_schema/*.yaml` | Done |
| 3. Validation & Cross-Reference | 3, 5 | `app/validation.py` | Done |
| 4. AI Enrichment & Manual Review | 6, 11 | `app/ai_enrichment.py` | Done |
| 5. Validation Views, Business Insights, Streamlit UI | 7, 7a, 8, 16 | `app/validation_views.py`, `app/business_metrics.py`, `streamlit_app.py` | Done |
| 6. Export incl. Optilogic-ready, Docs | 13 | `app/export.py` | Done |

## Datasets (all 8, canonical schema per dataset)

Master: `customer_master`, `location_master`, `vendor_master`, `product_master`
Transactional: `production_history`, `shipment_history`, `shipment_cost`, `inventory_history`

Canonical field definitions (including Optilogic/Cosmic Frog target field names)
live in `configs/canonical_schema/<dataset>.yaml`.

## Pipeline flow

```
Extraction (SQL Server w/ Windows Auth, or file upload, or sample data)
        -> Bronze (raw, immutable, as-extracted)
        -> Column Mapping (rule-based + fuzzy "AI-assisted" suggestion, human-approved)
        -> Silver (cleaned, standardized, canonical field names)
        -> Profiling (nulls, distributions, schema drift vs. previous run)
        -> Validation (mandatory fields, ranges, formats -> row_status)
        -> Cross-Reference (transactional FKs checked against master data)
        -> AI Enrichment (fills missing city/state/postal_code/lat/long, always flagged for review)
        -> Gold (modeling-ready, canonical schema, fully audited)
        -> Validation Views / Business Insights / Export (incl. Optilogic-ready CSV)
```

Every stage is versioned by `run_id`. Raw Bronze data is never mutated;
all cleaning/validation/enrichment results are added as new columns.

## SQL Server extraction (Windows Authentication)

`app/extraction.py` provides `SqlServerExtractor`, which connects using
`Trusted_Connection=yes` (no stored credentials). Example:

```python
from app.extraction import SqlServerExtractor

extractor = SqlServerExtractor(server="MYSQLSERVER", database="ERP_DB")
result = extractor.extract(
    dataset="customer_master",
    query="SELECT * FROM dbo.Customers",
    run_id="run_20260101T000000_abcd1234",
    project_id="my_project",
)
```

No live SQL Server is available in this dev environment, so the pipeline runner
defaults to a realistic **synthetic sample dataset** (`app/sample_data.py`) that
mimics an ERP export with different raw column names and intentional data-quality
issues (missing city/state, negative quantities, invalid references) — this is
what exercises every downstream stage in tests and the Streamlit demo.

## Running the pipeline

```bash
python -c "from app.pipeline import run_full_pipeline; print(run_full_pipeline('demo_project'))"
```

## Running the Streamlit app

```bash
streamlit run streamlit_app.py
```

Screens: run trigger, run history, profiling report, dataset quality dashboard,
issue explorer, cross-reference exceptions, AI-fill review queue, record detail
(raw vs. validated with Validated/All/Flagged filter), column mapping review,
Business Insights (customer volume distribution, product Pareto, inbound/outbound
flow, total spending, mode split — all filterable by validation status), and
export/download (including Optilogic-ready CSV).

## Running tests

```bash
python -m pytest tests/ -v
```

31 tests covering: column mapping (rule-based + fuzzy match, approval gating),
validation (mandatory fields, ranges, negative-value handling), cross-reference
checks, AI enrichment (evidence-based fill + mandatory review flagging),
profiling (null/distinct stats, schema drift), and a full end-to-end integration
test across all 8 datasets (extraction -> Gold -> views -> metrics -> export).

## Design principles enforced in code

- Raw Bronze data is immutable — `app/silver_etl.py` always reads Bronze and
  writes a new Silver artifact; never mutates in place.
- Canonical schema (`configs/canonical_schema/*.yaml`) ensures Silver/Gold
  column names are identical across every project regardless of source system
  naming — required for consistent Optilogic/Cosmic Frog import.
- AI-assisted column mappings and AI-assisted geo-fills are never auto-trusted:
  mappings require `approved=True`; every enrichment attempt creates a manual
  review item regardless of confidence (`app/ai_enrichment.py`).
- Every run is versioned by `run_id`; issue logs, review queues, and
  cross-reference exceptions are all persisted per run for auditability.

## Phase 2 — Production/Scale: FastAPI + React/Next.js

In addition to the Streamlit MVP, a production-grade architecture is now in place:

### FastAPI backend (`api/`)

A thin HTTP layer wrapping the same `app/` pipeline/views/metrics modules — no
business logic is duplicated. Run it with:

```bash
python -m uvicorn api.main:app --reload --port 8000
```

Key endpoints (see `api/main.py` for the full list):
- `POST /pipeline/run` — trigger a full pipeline run
- `GET /runs/{project_id}` — list runs; `GET /runs/{project_id}/{run_id}/summary`
- `GET /runs/{project_id}/{run_id}/quality` — dataset quality dashboard data
- `GET /runs/{project_id}/{run_id}/issues/{dataset}` — issue log
- `GET /runs/{project_id}/{run_id}/cross-reference-exceptions/{dataset}`
- `GET /runs/{project_id}/{run_id}/review-queue/{dataset}` + `POST /review/.../decision`
- `GET /views/{project_id}/{run_id}/{dataset}` — raw-vs-validated view (status_filter param)
- `GET /metrics/{project_id}/{run_id}/{metric_name}` — Plotly figure JSON (status_filter param)
- `GET /mappings/{project_id}/{dataset}` + `POST /mappings/.../approve`
- `POST /export/{project_id}/{run_id}` + `GET /export/.../optilogic`

### Next.js + TypeScript frontend (`frontend/`)

A professional enterprise-blue-themed dashboard built with Next.js (App Router),
MUI (Material UI), and Plotly.js, mirroring all 11 Streamlit screens plus a
persistent sidebar navigation and top app bar showing SQL connection status.

**Node.js is required and was not available in this dev environment** — the
code is fully scaffolded but has not been `npm install`'d or run. To use it:

1. Install [Node.js LTS](https://nodejs.org/) (v18.18+ or v20+).
2. Install dependencies and run the dev server:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. Open http://localhost:3000 (make sure the FastAPI backend from above is
   running on port 8000 first — CORS is pre-configured for this).
4. Optional: copy `frontend/.env.local.example` to `frontend/.env.local` to
   point at a different backend URL.

**Theme**: `frontend/src/theme/theme.ts` defines a layered blue enterprise
palette (deep navy `#0B3D91` primary, medium blue `#2D6CDF` secondary, sky
blue `#5B9BD5` accent) applied consistently across the app bar, sidebar,
buttons, chips, and Plotly charts (`CHART_BLUE_SEQUENCE`).

## Live SQL Server Connection

Live extraction is config-driven via `configs/extraction_sources.yaml`:

```yaml
connection:
  server: "SQLSRV01"          # your SQL Server host/instance
  database: "ERP_PROD"        # your database name
  driver: "ODBC Driver 17 for SQL Server"

datasets:
  customer_master:
    load_mode: full
    query: "SELECT * FROM dbo.CustomerMaster"
  # ... one entry per dataset
```

- Uses **Windows/Integrated Authentication** (`Trusted_Connection=yes`) — no
  credentials are ever stored in code or config.
- Once `server` and `database` are filled in, `run_full_pipeline()` (and the
  `/pipeline/run` API / frontend "Run Full Pipeline" button) automatically
  switches from sample data to live SQL extraction — no code changes needed.
- `pyodbc` and the "ODBC Driver 17 for SQL Server" driver are already
  installed/detected in this environment (`pyodbc.drivers()` confirmed it
  available) — you only need to fill in `server`/`database`/table names.
- To force sample data even when SQL is configured, call
  `run_full_pipeline(project_id, use_sample_data=True)` explicitly.

## Known limitations / next steps

- Live SQL Server extraction is wired end-to-end (config, extractor, pipeline
  auto-detection) but has not been tested against a real server, since none is
  reachable from this environment — fill in `configs/extraction_sources.yaml`
  and verify against your actual SQL Server before production use.
- AI enrichment/mapping use deterministic evidence-based heuristics in place of
  a live LLM API call; the function signatures (`_infer_value`, mapping
  suggestion) are designed so a real LLM call can be substituted without
  changing any calling code.
- The Next.js frontend is fully scaffolded but not yet run/built, since Node.js
  is not installed in this environment — install Node.js and run
  `npm install && npm run dev` inside `frontend/` to launch it.
- The Streamlit MVP (`streamlit_app.py`) remains available and fully functional
  as a lightweight alternative/fallback frontend.
