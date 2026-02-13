# InvoiceScope — Authoritative Project Plan

## 1. PROJECT GOAL

### End-State Vision

InvoiceScope is a backend-first financial ingestion and intelligence engine designed to:

- Ingest SaaS and cloud vendor invoices (PDF)
- Extract structured financial data
- Normalize vendors
- Validate financial correctness
- Maintain full audit history of parsing
- Provide deterministic reporting (monthly, MoM, trend, anomaly)
- Support rule-based + AI parsing
- Be production-ready for multi-tenant SaaS deployment

The system must behave like a **financial engine**, not a demo parser.

It must be:

- Deterministic  
- Auditable  
- Reproducible  
- Extendable (LLM integration later)  
- Safe for financial reporting  

---

## 2. CURRENT IMPLEMENTATION STATUS

### Backend

**Implemented**

- FastAPI application
- PostgreSQL via Docker Compose
- Alembic migrations
- Invoice model (with extracted financial fields)
- File upload endpoint
- File hashing for duplicate detection
- Extracted text storage
- Re-parse endpoint
- Vendor normalization (AWS, Azure, Freshdesk)
- Monthly report endpoint
- Month-over-month (MoM) report endpoint
- Trend report endpoint
- Anomalies endpoint (basic new_vendor logic)
- Parse-run architecture
- Dashboard UI
- Invoice detail page
- Parse history endpoint

**Partially Implemented**

- Validation logic (basic)
- `needs_review` flag
- Vendor canonicalization rules (hardcoded)
- Confidence modeling (not formalized)
- Error handling UX

**Missing / Not Yet Implemented**

- Full validation engine
- Confidence scoring framework
- Structured LLM parsing pipeline
- Multi-tenant support
- Role-based access control
- Currency normalization / FX logic
- Credit note handling
- Data export (CSV/API integration)
- Parser versioning strategy
- Structured financial audit log
- Rate limiting / auth
- SaaS billing boundaries

---

## 3. ARCHITECTURE OVERVIEW

### Backend Stack

- FastAPI
- SQLAlchemy ORM
- Alembic
- PostgreSQL
- Docker Compose
- Server-rendered HTML dashboard
- Rule-based parsing pipeline
- Parse run audit table

---

### Data Models

#### `invoices`

Core invoice table:

- id
- vendor_raw
- vendor_canonical
- invoice_number
- billing_period_start
- billing_period_end
- invoice_date
- currency
- total_amount
- tax_amount
- extracted_text
- file_hash
- file_path
- source
- needs_review
- last_parse_run_id
- created_at

#### `invoice_parse_runs`

Audit table:

- id
- invoice_id
- created_at
- parser_version
- parser_kind ("rules" | "llm")
- model_name
- status ("success" | "failed" | "needs_review")
- confidence (0..1 nullable)
- vendor_raw
- vendor_canonical
- invoice_number
- invoice_date
- billing_period_start
- billing_period_end
- currency
- total_amount
- tax_amount
- validation_errors (json/text)
- debug_info (json/text)

Invoices store current best values.  
Parse runs preserve historical attempts.

---

### Key Endpoints

#### Upload & Parse

- `POST /invoices/upload`
- `POST /invoices/{id}/parse`
- `GET /invoices/{id}`
- `GET /invoices/{id}/parse-runs`
- `GET /invoices/{id}/text`

#### Reporting

- `GET /reports/monthly`
- `GET /reports/monthly/mom`
- `GET /reports/trend`
- `GET /reports/anomalies`

#### Health

- `GET /health`

---

### Processing Flow

1. User uploads PDF
2. File hash computed
3. Duplicate detection (409 if exists)
4. PDF stored
5. Text extracted
6. Parse run created
7. Rule-based parsing applied
8. Validation applied
9. Parse run saved
10. If success → invoice updated with current fields
11. Reporting queries read only from invoice table

---

## 4. CONSTRAINTS & NON-GOALS

### Fixed Technology Choices

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Docker Compose
- Server-rendered dashboard

These must not change.

---

### Must Not Change

- Deterministic financial reporting
- Auditability of parsing
- No silent overwrites of financial fields
- Duplicate detection via file_hash
- Separation between invoice and parse runs

---

### Out of Scope (Current Phase)

- Payment reconciliation
- Bank feed integration
- OCR training
- Double-entry accounting ledger
- Multi-region infra

---

## 5. ROADMAP TO COMPLETION

### Phase 1 — Engine Hardening

Objective:
Make this a production-grade ingestion engine.

Deliverables:
- Strict validation rules
- Confidence scoring
- Deterministic `needs_review` logic
- Parser version discipline
- Reporting correctness improvements

---

### Phase 2 — AI Parsing Layer

Objective:
Add LLM extraction safely.

Deliverables:
- Structured schema extraction
- Confidence scoring
- Evidence snippet capture
- Fallback to rules
- Validation gate before accepting output

---

### Phase 3 — Financial Correctness Layer

Objective:
Harden financial math.

Deliverables:
- Currency-safe grouping
- No cross-currency aggregation
- FX conversion model (optional)
- Credit note detection
- Tax validation logic

---

### Phase 4 — SaaS Layer

Objective:
Multi-tenant SaaS platform.

Deliverables:
- `tenant_id` on all tables
- User table
- Authentication
- Plan limits
- API keys
- Usage boundaries

---

### Phase 5 — Production Readiness

Objective:
Operational stability.

Deliverables:
- Logging strategy
- Observability
- Rate limiting
- Backup strategy
- Data export
- Versioned parser releases

---

## 6. NEXT TASKS (PRIORITIZED)

### Priority 1 — Validation Engine

Implement strict validation rules:

- invoice_date required
- currency required
- total_amount ≥ 0
- billing_period_start ≤ billing_period_end
- tax_amount NULL ≠ 0
- total matches subtotal + tax (if available)

Update:

- `validation_errors` in parse_run
- auto-set `needs_review = true` if validation fails
- confidence reduction when warnings exist

---

### Priority 2 — Confidence Framework

Base score: 1.0

Adjustments:

- -0.3 missing invoice_date
- -0.2 missing currency
- -0.3 missing total_amount
- -0.2 conflicting totals

If confidence < 0.7 → mark `needs_review`

---

### Priority 3 — Reporting Hardening

- Never aggregate across currencies
- Exclude NULL tax from sum
- Handle:
  - new vendor
  - dropped vendor
  - zero vs NULL differences

---

### Priority 4 — Parser Version Discipline

- Hardcode `parser_version`
- Increment manually
- Store in parse runs
- Display in invoice detail page

---

### Priority 5 — LLM Integration Scaffold

- `parser_kind = "llm"`
- LLM parser interface (stub)
- Structured schema validation
- Mock mode support

---

## 7. DEFINITION OF DONE

InvoiceScope is considered complete when:

- All invoices processed through parse_runs
- No invoice fields silently overwritten
- All financial fields validated
- Confidence scoring visible
- `needs_review` works deterministically
- Reporting never mixes currencies
- MoM handles new/missing vendors
- Parse history immutable
- Docker boots cleanly
- Tests exist for:
  - parsing
  - validation
  - reporting math
  - duplicate detection

