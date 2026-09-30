```markdown
# plan.md

## Step-by-Step Plan to Build the Supply Chain Data Validation App

This document outlines the step-by-step process to create an application that validates and enriches supply chain datasets using AI agents while preserving raw input files unchanged.

The app must support these raw input datasets

### Master data
1. Customer master
2. Location master
3. Vendor master
4. Product master

### Transactional data
5. Production history
6. Shipment history
7. Shipment cost
8. Inventory history

The app must
- preserve raw input columns exactly as received
- create only new validated columns with standardized names
- validate mandatory fields by dataset
- cross-check transactional records against master tables
- use AI assistance only for missing citystateziplatitudelongitude values
- always flag AI-filled values for manual review

---

# 1. Define Product Scope

## Goal
Build an app that helps users upload supply chain raw files, validate them, enrich selected missing geographic fields, and generate validated datasets plus issue reports.

## Core outcomes
The app should
- ingest raw files
- profile schemas
- validate records based on dataset-specific rules
- create validated columns
- cross-check master and transactional data
- use AI-assisted fill for selected missing location attributes
- produce issue logs, manual review queues, and summary reports

## Deliverables
- validated datasets
- issue log
- cross-reference exception report
- manual review queue
- validation summary dashboard
- rule configuration layer
- audit trail

---

# 2. Define User Roles

Identify who will use the app.

## Primary users
- supply chain analysts
- master data analysts
- data stewards
- operations analysts
- data engineering team

## Optional users
- procurement analysts
- transportation analysts
- inventory planners
- plant operations analysts

## User needs
Users need to
- upload raw files
- map files to dataset types
- run validation jobs
- review issues
- review AI-assisted fills
- export validated outputs
- inspect data quality summaries

---

# 3. Define MVP Scope

Build a minimum viable product first.

## MVP datasets
Include
- customer master
- location master
- vendor master
- product master
- shipment history

## MVP features
- file upload
- dataset type selection
- raw column preservation
- validated column creation
- mandatory field checks
- product and location reference checks
- in-scope product detection from shipment history
- AI-assisted fill for citystatepostal_codelatitudelongitude
- manual review queue
- CSVXLSX export
- summary metrics

## Post-MVP datasets
Add later
- production history
- shipment cost
- inventory history

---

# 4. Define Business Rules Clearly

Before coding, formalize the rules.

## Master tables
For
- customer master
- location master
- vendor master

Validate
- ID
- city
- state
- zippostal code
- country
- latitude
- longitude

If citystateziplatitudelongitude is missing
- try AI-assisted fill into validated columns only
- do not modify raw columns
- always flag for manual review

## Product master
Validate
- ID
- product weight
- dimension
- pallet conversion
- product category or family

Cross-check
- shipment history outbound data
- mark products appearing in outbound shipments as in scope

## Shipment history
Validate
- origin
- destination
- product
- volume
- shipment mode

Cross-check
- product against product master
- origindestination against relevant master tables

## Other transactional tables
Support
- production history
- shipment cost
- inventory history

At MVP stage, define extensible placeholders and schema handling.

---

# 5. Design the App Architecture

Use a layered architecture.

## Recommended layers
1. ingestion layer
2. schema detection and dataset classification layer
3. validation engine
4. cross-reference engine
5. AI enrichment engine
6. issue logging and audit engine
7. review workflow layer
8. exportreporting layer
9. frontend UI
10. persistencestorage layer

## Recommended architecture style
- backend API
- workerasync job processor
- database
- objectfile storage
- frontend web app

---

# 6. Choose the Tech Stack

Pick tools before implementation.

## Suggested backend
- Python
- FastAPI

## Suggested data processing
- pandas or polars
- Great Expectations or custom validation framework
- fuzzy matching library if needed
- pydantic for schemas

## Suggested AI layer
- LLMAI agent orchestration
- prompt templates for controlled enrichment
- confidence scoring logic
- optional geocodingreference service integration

## Suggested frontend
- React  Next.js
- or Streamlit for fast prototype

## Suggested storage
- PostgreSQL for metadata, issues, and audit logs
- object storage for uploaded files and outputs

## Suggested async processing
- Celery  RQ  background workers

---

# 7. Define the Data Model

Create the internal data model before building.

## Core entities
- dataset
- upload_job
- validation_run
- record_issue
- manual_review_item
- cross_reference_exception
- column_mapping_metadata
- output_artifact

## Example tables
- `datasets`
- `uploaded_files`
- `validation_runs`
- `issue_logs`
- `manual_review_queue`
- `review_decisions`
- `exported_outputs`

## Must store
- dataset type
- upload timestamp
- file version
- validation status
- issue counts
- enrichment counts
- review status
- output file paths

---

# 8. Define Dataset Detection and File Registration

When a user uploads a file, the app should classify it.

## Steps
1. upload file
2. user selects dataset type or app recommends one
3. app stores original file unchanged
4. app creates a file registration entry
5. app reads headers and samples data
6. app links file to validation ruleset

## Important
Never rename raw file columns in stored source data.

---

# 9. Build the Column Understanding Layer

Because raw columns vary by source, create a mapping assistant.

## Goal
Interpret raw source columns without renaming them.

## The app should
- detect possible business meaning of raw columns
- map raw columns to business concepts internally
- use those concepts to create validated columns

## Example
If raw file contains
- `Cust ID`
- `ZIP`
- `Lat`

The app should internally understand them as
- customer_id
- postal_code
- latitude

But raw columns remain unchanged.

## Output
Store internal mapping metadata such as
- raw column name
- mapped business concept
- confidence
- rule source
- approved status

---

# 10. Build the Validation Engine

This is the core rules engine.

## Functions
- check mandatory fields
- check numeric ranges
- validate formats where applicable
- create validated columns
- create flags
- assign record validation status

## Required behavior
- raw columns remain unchanged
- validated columns are added only as new fields
- failed checks create issue log entries

## Implementation steps
1. load dataset
2. apply dataset-specific mapping
3. evaluate required fields
4. validate numeric ranges
5. populate validated columns
6. create missinginvalid flags
7. assign row-level status

---

# 11. Build the Cross-Reference Engine

This engine validates transactional files against master files.

## Required checks
- shipment product - product master
- shipment origin - relevant master
- shipment destination - relevant master
- production product - product master
- production location - location master
- inventory product - product master
- inventory location - location master

## Implementation steps
1. identify key reference fields
2. normalize matching logic internally
3. check existence in referenced master
4. write validated reference columns
5. create invalid reference flags
6. create exception report entries

---

# 12. Build the AI Enrichment Engine

Use AI only in a constrained way.

## Scope
Only fill missing
- city
- state
- postal_code
- latitude
- longitude

## Rules
- never write into raw fields
- only write into validated fields
- always create manual review item
- include confidence score
- include explanation

## Inputs for enrichment
- other columns in same record
- matching master records
- cross-dataset evidence
- trusted internal references
- optional external geographic reference service if approved

## Implementation steps
1. detect missing allowed fields
2. gather evidence
3. pass constrained prompt to agent
4. return candidate fill + rationale + confidence
5. populate validated field if confidence threshold met
6. always set manual review required
7. log evidence and action

---

# 13. Build the Manual Review Workflow

This is required because all AI-filled values need review.

## Manual review queue should include
- all AI-assisted fills
- ambiguous master reference matches
- unresolved invalid references
- low-confidence mapping cases

## Reviewer actions
- approve validated value
- reject validated value
- replace with corrected value
- mark as unresolved

## Needed features
- row-level side-by-side raw vs validated view
- issue explanation
- confidence display
- audit trail
- reviewer comments

---

# 14. Build the Issue Logging and Audit Layer

Every important action must be logged.

## Log
- validation rule failures
- missing mandatory fields
- invalid numeric values
- invalid references
- AI-assisted fills
- manual review decisions

## Each log entry should contain
- dataset_name
- file_id
- record_id
- raw_column_name
- validated_column_name
- issue_type
- issue_description
- severity
- raw_value
- validated_value
- confidence_score
- manual_review_required
- created_at

---

# 15. Build the Output Generator

The app should generate user-friendly outputs.

## Required outputs
1. validated dataset
2. issue log
3. manual review queue
4. exception report
5. validation summary

## Export formats
- CSV
- XLSX
- optional Parquet

## Output rules
- include raw columns unchanged
- append validated columns
- append flags and status fields
- do not suppress failed rows unless explicitly requested

---

# 16. Build the Summary Dashboard

The app should provide quick quality visibility.

## Dashboard metrics
- total records processed
- total valid records
- total invalid records
- total manual review records
- missing field counts by dataset
- invalid reference counts
- AI-assisted fill counts
- in-scope product counts
- top recurring issues

## Views
- dataset summary
- field quality summary
- issue severity summary
- review queue summary

---

# 17. Build Configuration Support

Make rules configurable instead of hard-coded.

## Config should support
- dataset type rules
- mandatory fields by dataset
- business concept mapping aliases
- outbound shipment logic
- accepted units
- confidence thresholds
- manual review policies

## Suggested format
- YAML or JSON

---

# 18. Build Dataset-Specific Pipelines

Implement validation in phases.

## Phase 1
- customer master
- location master
- vendor master

## Phase 2
- product master
- shipment history

## Phase 3
- production history
- shipment cost
- inventory history

This phased approach reduces complexity and speeds up MVP delivery.

---

# 19. Define API Endpoints

If building a backend API, define endpoints early.

## Suggested endpoints
- `POST upload`
- `POST validate`
- `GET runs{id}`
- `GET runs{id}summary`
- `GET runs{id}issues`
- `GET runs{id}review-queue`
- `POST review{item_id}decision`
- `GET runs{id}export`

---

# 20. Define Frontend Screens

## Essential screens
1. upload screen
2. dataset registrationmapping screen
3. validation run status screen
4. issue explorer
5. manual review queue
6. record detail view
7. exportdownload page
8. dashboard page

---

# 21. Define Step-by-Step Build Sequence

## Step 1 finalize business rules
- confirm required fields by dataset
- confirm outbound logic for product scope
- confirm origindestination matching rules
- confirm confidence thresholds

## Step 2 create repository structure
Suggested folders
- `app`
- `backend`
- `frontend`
- `workers`
- `configs`
- `prompts`
- `tests`
- `docs`

## Step 3 set up backend project
- initialize API framework
- set up database connection
- create file storage integration
- create job runner

## Step 4 create metadata database schema
- files
- runs
- issues
- review items
- outputs
- config versions

## Step 5 implement file upload and dataset registration
- upload raw file
- assign dataset type
- save unchanged original
- extract headers

## Step 6 implement internal column concept mapping
- raw column - business concept
- store confidence and mapping source

## Step 7 implement master table validation engine
- customer master
- location master
- vendor master

## Step 8 implement product master validation
- required fields
- in-scope logic

## Step 9 implement shipment history validation
- required fields
- master cross-checks

## Step 10 implement AI enrichment engine
- missing citystatepostal_codelatitudelongitude
- constrained prompt
- confidence scoring
- manual review creation

## Step 11 implement issue logs and review queue
- create issue records
- create manual review items
- add audit metadata

## Step 12 implement exports
- validated dataset
- logs
- review files
- summaries

## Step 13 build frontend screens
- upload
- run status
- issue browser
- review queue
- dashboard

## Step 14 add remaining datasets
- production history
- shipment cost
- inventory history

## Step 15 test with real samples
- validate quality rules
- test badmissing data cases
- test AI fill cases
- test review workflow

## Step 16 harden for production
- auth
- access control
- retry logic
- observability
- performance tuning

---

# 22. Testing Plan

## Unit tests
Test
- mandatory field checks
- numeric range checks
- validated column generation
- reference matching logic
- issue creation logic

## Integration tests
Test
- full dataset validation run
- file upload to export flow
- master and transactional cross-checks
- AI enrichment with manual review creation

## User acceptance tests
Test
- analyst upload workflow
- issue inspection
- review queue resolution
- export quality

## Regression tests
Maintain sample files with
- complete valid data
- missing mandatory values
- broken references
- duplicate edge cases
- AI-enrichable geographic gaps

---

# 23. Security and Governance

## Requirements
- preserve source data immutability
- log all changes and review actions
- secure uploaded files
- control access to sensitive datasets
- maintain run history
- version prompts and configs

## Governance rule
AI-assisted values are suggestions in validated columns and must not be treated as confirmed truth until reviewed if business policy requires it.

---

# 24. Suggested Milestones

## Milestone 1
Foundation
- repo setup
- upload flow
- dataset registration
- database schema

## Milestone 2
Validation MVP
- master data validation
- product validation
- shipment history validation
- issue logs
- exports

## Milestone 3
AI enrichment
- constrained fill logic
- confidence scoring
- manual review workflow

## Milestone 4
UI and dashboard
- issue browser
- review queue
- summary dashboard

## Milestone 5
Expanded transactional support
- production history
- shipment cost
- inventory history

## Milestone 6
Production readiness
- auth
- monitoring
- performance
- documentation

---

# 25. Success Criteria

The app is successful when it can

- ingest all required raw datasets
- preserve raw columns unchanged
- create validated columns only
- catch missing mandatory fields accurately
- cross-check references reliably
- fill selected missing geographic fields using AI assistance
- flag every AI-filled value for manual review
- generate clear issue logs and exportable outputs
- support iterative review and correction

---

# 26. Final Build Guidance

Build the app in this order

1. file ingestion
2. dataset registration
3. internal column concept mapping
4. rule-based validation engine
5. cross-reference engine
6. issue logging
7. export generation
8. AI enrichment engine
9. manual review workflow
10. dashboard and UX improvements

Keep the design conservative
- raw columns untouched
- validated columns added only
- AI limited to approved enrichment fields
- all AI-assisted fills flagged for review
- all outputs fully auditable

---
```