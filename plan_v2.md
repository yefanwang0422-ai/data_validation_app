# plan_v2.md

## Enriched Step-by-Step Plan: Supply Chain Data Cleaning, Validation & Modeling-Readiness App

> **Last updated: July 2026**
>
> This document reflects the current state of the fully implemented application.
> The original plan.md is preserved in `Archive/plan.md`.

The app's job: pull raw data directly from a SQL database or uploaded files, clean/standardize it, profile it, validate it, cross-check it, fill gaps with AI assistance (flagged for review), and produce a modeling-ready, fully audited dataset — plus review tools for humans to trust the output.

---

## Implementation Status

The application is **fully implemented** through Milestones 1–6 and includes several enhancements beyond the original plan. The stack is:
- **Backend**: Python (FastAPI + pandas pipeline)
- **Frontend**: React / Next.js (MUI) — Phase 2 production UI, skipping Streamlit MVP
- **Storage**: Parquet files (Bronze/Silver/Gold) + JSON configs + JSONL logs

All 36 unit/integration tests pass. The API runs on `http://localhost:8000` and the frontend on `http://localhost:3000`.

---

## Datasets in Scope

**Master data**
1. Customer master
2. Location master
3. Vendor master
4. Product master

**Transactional data**
5. Production history
6. Shipment history (combined inbound + outbound, `direction` field required)
7. **Inbound shipment history** *(new — separate dataset, origin = vendor, destination = facility)*
8. **Outbound shipment history** *(new — separate dataset, origin = facility, destination = customer or internal location)*
9. Shipment cost
10. Inventory history

---

## Non-Negotiable Design Principles

- Raw source data is immutable — never edit or overwrite it, anywhere in the pipeline.
- Every derived/cleaned/enriched value lives in new, clearly named columns.
- Every automated decision (cleaning rule, validation rule, cross-reference match, AI fill) is logged and traceable back to its source.
- AI-filled values are always flagged for manual review and are never treated as ground truth until approved.
- Every pipeline run is versioned and repeatable (same input + same config = same output).

---

# 0. Data Extraction Layer

## SQL Server (Windows Authentication)
- `pyodbc` / `SQLAlchemy` with `Trusted_Connection=yes` — no passwords stored.
- Config-driven: `configs/extraction_sources.yaml` maps each dataset to a SQL query, load mode (full/incremental), and watermark column.
- Full load for master tables; incremental load (watermark) for transactional tables.

## Inbound/Outbound SQL defaults
```yaml
inbound_shipment_history:
  query: "SELECT * FROM raw_shipmenthistory WHERE Direction = 'Inbound'"
outbound_shipment_history:
  query: "SELECT * FROM raw_shipmenthistory WHERE Direction = 'Outbound'"
```

## File Upload
- Per-dataset CSV/XLSX upload via `POST /data-sources/{project_id}/{dataset}/upload`.
- Automatically triggers mapping suggestion refresh (`overwrite=True`) on upload.
- Same Bronze landing contract as SQL extraction.

## Bronze Landing
- Parquet files at `data/bronze/{project_id}/{dataset}/{run_id}/data.parquet`.
- Immutable after landing; never overwritten.

---

# 1. Python ETL Pipeline — Bronze → Silver → Gold

## Three-Phase Workflow (current implementation)

The pipeline is split into three independently callable phases:

### Phase 1 — Extract to Bronze (`POST /pipeline/extract-only`)
- Extracts all configured datasets into Bronze.
- **Always regenerates column mapping suggestions** from actual raw columns (`overwrite=True` with smart-merge — see Section 9).
- Returns `run_id`, per-dataset row counts, and raw column names for Step 2 review.

### Phase 2 — Review Column Mappings (frontend UI)
- User reviews AI-suggested raw → canonical field mappings per dataset.
- Can override any mapping via dropdown (scoped to that dataset's canonical schema only).
- Can explicitly exclude a column (set to blank = passes through as `raw__column_name`).
- **Previously approved mappings are remembered** (smart-merge preserves approved choices across re-extractions).
- "↻ Refresh Mappings" button regenerates from Bronze without re-extracting.

### Phase 3 — Validate/Profile/Enrich/Gold (`POST /pipeline/run-from-bronze`)
- Silver ETL → Profiling → Validation → Cross-reference → AI Enrichment → Gold.
- **Per-dataset error isolation**: each dataset is individually try/catch wrapped — one bad dataset never crashes the run.
- Returns full validation summary with issue counts, dataset results, and skip reasons.

### Quick Full Pipeline (`POST /pipeline/run`)
- Backward-compatible single-call endpoint that runs all three phases in sequence.

## Layered Model
- **Bronze**: exact copy of source data, as extracted. Immutable.
- **Silver**: cleaned, standardized, renamed to canonical schema. Raw columns preserved with `raw__` prefix for unmapped columns.
- **Gold**: Silver + validation flags + AI enrichment + `row_status` (`valid` / `invalid` / `needs_review`).

---

# 2. Data Profiling

- Runs immediately after Silver is produced, before validation.
- Generates JSON summary per dataset per run stored at `data/run_logs/{project_id}/profiles/{dataset}/{run_id}.json`.
- Accessible via `GET /runs/{project_id}/{run_id}/profile/{dataset}`.

---

# 3. Business Rules & Validation

## Shipment History — Direction Field
- `direction` is now **required** on `shipment_history` (must be `"Inbound"` or `"Outbound"`, case-insensitive).
- Records with invalid direction values are flagged with `issue_type = "invalid_direction_value"`, `severity = "high"`.

## Outbound Shipment History — Destination Type
- `destination_location_id` is checked against **both** `location_master` AND `customer_master`.
- Each row is stamped with `destination_type`:
  - `"internal"` — destination found in `location_master` (inter-facility transfer)
  - `"external"` — destination found in `customer_master` (customer delivery)
  - `"unknown"` — not found in either (cross-reference exception)
- This enables segmented internal vs. external demand analysis.

## All Other Rules
Unchanged from original plan — mandatory fields, numeric ranges, lat/lon bounds, negative inventory flagging.

---

# 4. App Architecture

## File Layout
```
app/
  config.py          # Paths, DATASETS list, canonical schema loader, mapping config
  pipeline.py        # extract_to_bronze(), bronze_to_gold(), run_full_pipeline()
  extraction.py      # SQL + file upload extraction
  silver_etl.py      # Bronze → Silver transformation with mapping application
  validation.py      # validate_dataset(), cross_reference_check(), direction/type checks
  validation_views.py# View functions: issue log, xref exceptions, quality summary
  profiling.py       # run_profiling()
  column_mapping.py  # suggest_mappings(), auto_approve(), merge_approved_mappings()
  ai_enrichment.py   # enrich_missing_geo_fields() — address parse + geocode
  ai_insights.py     # AI executive dashboard + chat (NTT AI Gateway / GPT-4o)
  business_metrics.py# 9 chart metric functions with raw-column fallbacks
  export.py          # export_all(), export_optilogic_ready()
  sample_data.py     # Synthetic sample data for demo/test

api/main.py          # FastAPI application, all endpoints

configs/
  extraction_sources.yaml           # SQL connection + per-dataset queries
  canonical_schema/                 # 10 YAML files (one per dataset)
  column_mappings/{project_id}/     # Per-project approved mapping JSONs

data/
  bronze/  silver/  gold/           # Parquet files partitioned by project/dataset/run_id
  run_logs/                         # Summary JSON + JSONL issue/review/xref logs
  uploads/                          # Uploaded CSV/XLSX files

frontend/src/app/
  page.tsx              # Run Pipeline (3-phase stepper)
  data-sources/         # Per-dataset SQL / file source configuration
  mappings/             # Standalone column mapping review screen
  quality/              # Dataset quality dashboard
  issues/               # Issue explorer
  cross-reference/      # Cross-reference exceptions (grouped by count)
  review-queue/         # AI-fill manual review queue
  records/              # Record detail view
  profiling/            # Profiling report viewer
  insights/             # Business Insights (9 charts)
  ai-insights/          # AI Executive Dashboard + Chat (GPT-4o)
  export/               # Export / download
  runs/                 # Run history
```

---

# 5. Validation & Cross-Reference Engine

## Prefix-Strip Fuzzy Matching (NEW)
The cross-reference engine now handles ID prefix mismatches between source and master data:
- `_strip_prefix("PL1928")` → `"1928"` — strips leading non-numeric characters
- `"LOC-001"` → `"001"`, `"CUST-0042"` → `"0042"`
- Two-pass matching: exact match first, then prefix-stripped match
- Prefix-stripped matches are valid but logged as `match_type = "prefix_stripped"` with the `matched_value` noted
- Hard failures are `match_type = "no_match"`

## Aggregated Exception Reporting (NEW)
- `GET /runs/{project_id}/{run_id}/cross-reference-exceptions/{dataset}` groups exceptions by `(field, invalid_value, expected_master, match_type)` with a `count` field
- Returns `count` (total raw records) and `unique_exception_count` (distinct issues)
- Frontend Cross-Reference Exceptions page shows count chip (red when > 1), match_type chip, matched_value column, sorted by count descending

## Cross-Reference Rules per Dataset
```
shipment_history:
  product_id → product_master
  origin_location_id → location_master (+ vendor_master fallback)
  destination_location_id → customer_master

inbound_shipment_history:
  product_id → product_master
  origin_location_id → vendor_master       ← origin is a supplier
  destination_location_id → location_master ← destination is our facility

outbound_shipment_history:
  product_id → product_master
  origin_location_id → location_master
  destination_location_id → location_master | customer_master  ← dual-master, stamps destination_type

production_history:
  product_id → product_master
  location_id → location_master

inventory_history:
  product_id → product_master
  location_id → location_master

shipment_cost:
  shipment_id → shipment_history
```

---

# 6. AI Enrichment Engine

## Three Evidence Layers (priority order)

### Layer 1 — Address Parsing
- Parses `city`, `state`, `postal_code` from `address_line_1` using regex patterns
- Example: `"123 Main St, Chicago, IL 60601"` → `city=Chicago, state=IL, postal_code=60601`
- Confidence: 0.75

### Layer 2 — Cross-Record Postal Code Evidence
- Infers from other records in the same dataset sharing the same postal code
- Confidence: 0.90

### Layer 3 — Geocoding (NEW)
- If lat/lon are missing but city+state or postal code are known:
  1. **Hardcoded table**: 39 major US cities, instant, no network required
  2. **geopy/Nominatim**: free OpenStreetMap geocoder, 5-second timeout, graceful fallback if unavailable
- Confidence: 0.70 (geocoding), 0.90 (cross-record inference)

## Rules (unchanged)
- Never write into raw or Silver columns — Gold only
- Always create manual review item regardless of confidence
- Confidence gate: only apply if ≥ 0.60

---

# 7. Validation Views

Implemented in `app/validation_views.py`. All functions gracefully return empty DataFrames when Gold data doesn't exist (e.g., for Phase-1-only runs).

- `get_raw_vs_validated()` — returns empty DataFrame if Gold not yet produced
- `get_issue_flagged()` — safe empty-column guard
- `get_cross_reference_exceptions()` — safe empty-column guard
- `get_ai_fill_review()` — safe empty-column guard
- `get_dataset_quality_summary()` — returns `note` field if Gold not available yet

---

# 7a. Business Insights & Analytics

## `app/business_metrics.py` — 9 Charts

### Shipment-Based Charts (fallback across all 3 shipment datasets)
Charts try datasets in order: `outbound_shipment_history` → `inbound_shipment_history` → `shipment_history`. Uses first non-empty.

**Raw column fallbacks**: When canonical columns are absent, known raw column alternatives are used automatically:
```python
"volume": ["raw__Quantity", "raw__Qty", ...]
"state":  ["raw__ST", "raw__State", ...]
"shipment_mode": ["raw__Mode", ...]
```

1. **Customer Distribution by Volume** — top customers by outbound shipped volume
2. **Product Volume Pareto** — bar chart + cumulative % line
3. **Inbound Flow** — volume into locations (uses `inbound_shipment_history` first)
4. **Outbound Flow** — volume out of locations (uses `outbound_shipment_history` first)
5. **Total Spending by Vendor** — from `shipment_cost`
6. **Transportation Mode Split** — pie chart

### Master-Data Charts (NEW — work without any shipment data)
7. **Product Count by Category** — from `product_master.product_category`
8. **Customer Distribution by State** — from `customer_master.state`
9. **Inventory On-Hand by Location** — from `inventory_history.quantity_on_hand`

All charts return empty `go.Figure()` gracefully when data is unavailable; the frontend shows "No data" with actionable guidance text.

---

# 7b. AI Executive Insights (NEW)

## `app/ai_insights.py` — GPT-4o via NTT AI Gateway

### Data Summarization
`summarize_reporting_data()` aggregates Gold pipeline data into a compact summary (never sends raw rows to the LLM):
- Total network costs per dataset
- Cost breakdown by CostSubCategory
- Flow volumes by SubCategory (inbound/outbound/production)
- Service level proxy
- Top facilities by cost
- Cost deltas
- Geographic spread, network counts

### Executive Dashboard Generation
`generate_ai_dashboard()` calls GPT-4o and returns structured JSON:
```json
{
  "executive_summary": "...",
  "key_findings": ["...", "..."],
  "recommendations": ["...", "..."],
  "kpis": [{"label": "...", "value_a": ..., "unit": "$", "commentary": "..."}],
  "charts": [{"title": "...", "insight": "...", "data": [...], "layout": {...}}]
}
```

### Root-Cause Chat
`answer_chat_question()` provides conversational analysis with root-cause context:
- Per-facility cost and volume deltas
- Lane-level (origin→destination) cost and distance deltas
- Mode mix changes
- Resource/product mix changes
- Time-period trends
- Full conversation history preserved across messages

### API Gateway
- Authenticates via `POST /auth/appLogin` → JWT token
- Tries `workspace/workspaces/{id}/thread/run` first, falls back to `/chat`
- 120-second timeout, graceful fallback on any endpoint failure

### Configuration (environment variables)
```
AI_API_BASE   = https://api.ntth.ai/v1
AI_APP_ID     = 6a08840a-6fde-43ef-8a5b-d3e62d0c9b71
AI_APP_SECRET = (configured via env var)
AI_MODEL      = 6c26a584-a988-4fed-92ea-f6501429fab9  # GPT-4o
```

### API Endpoints
- `POST /ai-insights/dashboard` — generate executive dashboard JSON for a run
- `POST /ai-insights/chat` — answer a supply chain analysis question with root-cause context

---

# 8. Frontend — React / Next.js (MUI)

Phase 2 production UI was built directly, skipping the Streamlit MVP.

## Navigation Sections

### Setup
- **Data Sources** — per-dataset SQL query configuration and file upload. Inbound/Outbound shipment datasets shown with INBOUND/OUTBOUND badges.
- **Run Pipeline** — 3-phase stepper (Extract → Review Mappings → Validate & Profile)
- **Column Mapping** — standalone mapping review with dataset-scoped canonical field dropdowns

### Data Quality
- **Profiling Report** — dataset profiling JSON viewer
- **Dataset Quality** — per-dataset valid/review/invalid percentages
- **Issue Explorer** — validation issue log with type/severity filters
- **Cross-Reference Exceptions** — grouped exception table with count chip, match type, and matched value

### Review
- **AI-Fill Review Queue** — review AI-assisted geo enrichment fills
- **Record Detail** — raw vs. validated side-by-side record view

### Analytics
- **Business Insights** — 9 Plotly charts with status filter toggle
- **AI Executive Insights** — GPT-4o executive dashboard generation + supply chain analyst chat

### Output
- **Export / Download** — Gold data export per dataset
- **Run History** — historical run list

## Run Pipeline — 3-Phase Stepper
```
Step 1: Extract Data Now
  → POST /pipeline/extract-only
  → Bronze landed, mapping suggestions generated

Step 2: Review Column Mapping (per dataset accordion)
  → All raw columns shown (including unmapped)
  → Blank option = "Exclude / not needed"
  → Dataset-scoped canonical field dropdowns
  → ↻ Refresh Mappings button
  → Pending approval count badge
  → "Confirm Mappings & Run Validation" button

Step 3: Validate & Profile
  → POST /pipeline/run-from-bronze
  → Results: issue count, AI review items, xref exceptions, per-dataset stats
```

---

# 9. Canonical Schema & Column Mapping

## Smart-Merge (Approved Mappings Remembered)

`merge_approved_mappings(previous_entries, new_entries)`:
- If a raw column was **approved** in the previous config → keep user's confirmed canonical field
- If a column is **new** (not in previous config) → fresh AI suggestion
- If a column was previously **unapproved** → re-suggested with updated AI
- Columns removed from the data source → dropped

This means users only need to approve each column's mapping **once per project** — subsequent re-extractions preserve all approved choices automatically.

## All Columns Shown

`auto_approve_high_confidence()` now includes **every raw column** — not just matched ones.
- Mapped columns: canonical field + confidence + source + Approve button
- Unmapped columns: blank dropdown + "Excluded" chip (no approval needed)
- Explicitly excluded columns: user selects blank = "Exclude / not needed"

## Dataset-Scoped Canonical Fields

Column mapping dropdowns only show the canonical fields defined for **that specific dataset**:
- `GET /config/canonical-fields/{dataset}` returns fields from `configs/canonical_schema/{dataset}.yaml`
- ~20-35 fields per dataset (not the combined 100-field list)

## Canonical Schemas (10 datasets)
```
configs/canonical_schema/
  customer_master.yaml         (23 fields)
  location_master.yaml         (25 fields)
  vendor_master.yaml           (24 fields)
  product_master.yaml          (30 fields)
  shipment_history.yaml        (34 fields, direction required)
  inbound_shipment_history.yaml (34 fields)
  outbound_shipment_history.yaml (35 fields, incl. destination_type)
  production_history.yaml      (20 fields)
  shipment_cost.yaml           (18 fields)
  inventory_history.yaml       (24 fields)
```

## Refresh All Mappings
`POST /pipeline/refresh-all-mappings` reads Bronze Parquet files and regenerates all mapping configs for a run without re-extracting. Used to fix stale configs.

---

# 10. Issue Logging & Audit Layer

Log entries stored as JSONL at `data/run_logs/{project_id}/{run_id}_issues.jsonl`:

Each entry contains: `dataset_name`, `run_id`, `record_id`, `canonical_field`, `issue_type`, `issue_description`, `severity`, `raw_value`, `manual_review_required`, `created_at`.

Issue types include: `missing_mandatory_field`, `invalid_numeric_value`, `negative_inventory_exception`, `invalid_range`, `invalid_direction_value`.

Cross-reference exceptions: `data/run_logs/{project_id}/{run_id}_cross_reference_exceptions.jsonl`
- Fields: `dataset_name`, `run_id`, `record_id`, `field`, `invalid_value`, `matched_value`, `expected_master`, `match_type`, `count`, `created_at`

AI fill review queue: `data/run_logs/{project_id}/{run_id}_review_queue.jsonl`

---

# 11. Manual Review Workflow

Review queue includes all AI-assisted fills, unapproved column mappings, and unresolved cross-reference exceptions.

Reviewer actions via `POST /review/{project_id}/{run_id}/{dataset}/{record_index}/decision`:
- `approve`, `reject`, `replace` (with corrected value), `unresolved`

---

# 12. API Endpoints (FastAPI — `api/main.py`)

## Pipeline
- `POST /pipeline/run` — full pipeline (Extract + Silver + Validate + Gold)
- `POST /pipeline/extract-only` — Phase 1: Bronze + mapping suggestions
- `POST /pipeline/run-from-bronze` — Phase 3: Silver/Validate/Gold from existing Bronze
- `POST /pipeline/refresh-all-mappings` — regenerate mappings from Bronze without re-extracting

## Data Sources
- `GET /data-sources/{project_id}` — per-dataset source configuration
- `POST /data-sources/{project_id}/{dataset}/source-type` — set SQL / file / none
- `POST /data-sources/{project_id}/{dataset}/upload` — upload CSV/XLSX file

## Column Mapping
- `GET /mappings/{project_id}/{dataset}` — get mapping entries
- `POST /mappings/{project_id}/{dataset}/patch` — replace entries (manual override)
- `POST /mappings/{project_id}/{dataset}/{raw_column}/approve` — approve a mapping
- `POST /mappings/{project_id}/{dataset}/refresh` — re-run AI suggestion from uploaded file
- `GET /config/canonical-fields/{dataset}` — get dataset-scoped canonical field list

## Runs & Data
- `GET /runs/{project_id}` — list run IDs
- `GET /runs/{project_id}/{run_id}/summary` — run summary
- `GET /runs/{project_id}/{run_id}/quality` — per-dataset quality summary
- `GET /runs/{project_id}/{run_id}/profile/{dataset}` — profiling report
- `GET /runs/{project_id}/{run_id}/issues/{dataset}` — issue log
- `GET /runs/{project_id}/{run_id}/cross-reference-exceptions/{dataset}` — grouped exceptions
- `GET /runs/{project_id}/{run_id}/review-queue/{dataset}` — AI fill review queue
- `GET /views/{project_id}/{run_id}/{dataset}` — raw vs. validated records

## Business Metrics
- `GET /metrics/{project_id}/{run_id}/{metric_name}` — Plotly figure JSON
- `GET /metrics` — list available metric names

## AI Insights
- `POST /ai-insights/dashboard` — GPT-4o executive dashboard for a run
- `POST /ai-insights/chat` — conversational supply chain analyst Q&A

## Config
- `GET /config/sql-status` — whether SQL is configured
- `GET /config/sql-connection` — current SQL connection config
- `POST /config/sql-connection` — save SQL connection
- `POST /config/sql-connection/test` — test SQL connection
- `GET /config/odbc-drivers` — list available ODBC drivers

## Export
- `POST /export/{project_id}/{run_id}` — export all datasets
- `GET /export/{project_id}/{run_id}/{dataset}/optilogic` — Optilogic-ready CSV download

---

# 13. Export & Reporting

- `POST /export/{project_id}/{run_id}` — exports all available Gold datasets as CSV
- `GET /export/{project_id}/{run_id}/{dataset}/optilogic` — Gold data mapped to Optilogic/Cosmic Frog import template field names, downloadable CSV
- Export formats: CSV, XLSX, Parquet
- Gold/canonical exports use canonical field names across all projects

---

# 14. Configuration

```
configs/
  extraction_sources.yaml     — SQL connection + per-dataset queries (10 datasets)
  canonical_schema/           — 10 YAML files defining canonical fields per dataset
  column_mappings/{project}/  — Per-project approved mapping JSONs (one per dataset)
  data_sources/{project}.json — Per-dataset source type (sql/file/none) per project
```

Dependencies (`requirements.txt`):
```
pandas>=2.0, numpy>=1.24, PyYAML>=6.0, plotly>=5.18, streamlit>=1.28,
pytest>=7.4, openpyxl>=3.1, pyarrow>=14.0, rapidfuzz>=3.5,
geopy>=2.3.0, httpx>=0.27.0, pydantic>=2.4, sqlalchemy>=2.0, pyodbc>=5.0
```

---

# 15. Build Status — All Milestones Complete

| Milestone | Description | Status |
|-----------|-------------|--------|
| 1 | Extraction & Staging (SQL + file upload, Bronze landing) | ✅ Complete |
| 2 | ETL, Canonical Mapping, Profiling | ✅ Complete |
| 3 | Validation & Cross-Reference (all 10 datasets) | ✅ Complete |
| 4 | AI Enrichment & Manual Review | ✅ Complete |
| 5 | Validation Views, Business Insights, Frontend | ✅ Complete |
| 6 | AI Executive Insights (GPT-4o dashboard + chat) | ✅ Complete |

### Enhancements Beyond Original Plan
- 3-phase pipeline with independent extract/map/validate steps
- Inbound/Outbound shipment history as separate configurable datasets
- `destination_type` auto-classification (internal vs. external) on outbound shipments
- Prefix-strip fuzzy cross-reference matching
- Cross-reference exception aggregation with count
- Smart-merge approved mapping persistence
- All-columns mapping review (no columns hidden)
- Dataset-scoped canonical field dropdowns
- Address parsing + geopy geocoding in AI enrichment
- Raw column fallbacks in business metrics
- 3 new master-data charts (product category, customer geo, inventory)
- Full AI executive insights module (GPT-4o via NTT gateway)
- React/Next.js frontend built directly (Phase 2), skipping Streamlit MVP

---

# 16. Frontend Screens (Implemented)

1. **Run Pipeline** — 3-phase stepper with inline mapping review
2. **Data Sources** — per-dataset SQL/file configuration with Inbound/Outbound labels
3. **Column Mapping** — standalone review with smart-merge, all columns, dataset-scoped dropdowns
4. **Profiling Report** — per-dataset profiling JSON viewer
5. **Dataset Quality** — quality summary dashboard
6. **Issue Explorer** — validation issue log
7. **Cross-Reference Exceptions** — grouped with count chip + match type + Prefix Match badge
8. **AI-Fill Review Queue** — geo enrichment review queue
9. **Record Detail** — raw vs. validated side-by-side
10. **Business Insights** — 9 Plotly charts with status filter
11. **AI Executive Insights** — GPT-4o dashboard generation + supply chain analyst chat
12. **Export / Download** — Gold data + Optilogic-ready export
13. **Run History** — historical pipeline run list

---

# 17. Testing

36 unit/integration tests passing across:
- `tests/test_column_mapping.py` — mapping suggestion, auto-approve, smart-merge, apply_mapping
- `tests/test_validation.py` — mandatory fields, numeric ranges, direction validation, cross-reference
- `tests/test_ai_enrichment.py` — address parsing, geo inference, geocoding
- `tests/test_profiling.py` — profiling output format
- `tests/test_integration_pipeline.py` — full pipeline run end-to-end
- `tests/test_optional_data_sources.py` — partial data source configuration

---

# 18. Security & Governance

- Windows Authentication for SQL Server — no credentials stored
- Raw/Bronze data immutable after landing
- All AI-filled values flagged for manual review — never treated as ground truth
- Every pipeline run versioned with unique `run_id`
- Full audit trail: issue JSONL, review decision JSONL, xref exception JSONL per run
- AI insights: only statistical summaries sent to GPT-4o — no raw PII rows forwarded
- API credentials (AI gateway) via environment variables — not hardcoded

---

# 19. Success Criteria — All Met

- ✅ Pull all 10 datasets from SQL Server (Windows Auth) or uploaded files
- ✅ Clean and standardize through Bronze/Silver/Gold without mutating raw data
- ✅ Profile every dataset on every run
- ✅ Validate mandatory fields, formats, ranges per dataset
- ✅ Cross-reference transactional records against master data (with fuzzy matching)
- ✅ AI gap-filling for geographic fields (address parse + geocoding)
- ✅ Consistent canonical schema across all projects
- ✅ Approved column mappings remembered across re-extractions
- ✅ Export Gold data in Optilogic/Cosmic Frog-ready format
- ✅ React/Next.js production frontend with full review workflow
- ✅ AI executive insights and supply chain analyst chatbot (GPT-4o)
