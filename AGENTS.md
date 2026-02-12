# Project: InvoiceScope (self-hosted)

Goal:
- Self-hosted tool that consolidates invoices from emails/platforms into a database,
  then provides spend analytics (top vendors, monthly trends, spike detection).
- v0 scope: manual upload of invoice PDFs -> parse basic fields -> store in Postgres -> basic UI list.

Tech choices (v0):
- Backend: FastAPI (Python)
- DB: Postgres
- Parsing: extract PDF text (no OCR initially), regex/vendor heuristics
- Queue/worker: optional for v0; if used, use a simple worker (RQ/Celery) + Redis
- Frontend: minimal (could be simple HTML templates or a tiny React later)

Data model (minimum fields):
- invoices: id, vendor, vendor_domain, invoice_number, billing_period_start, billing_period_end,
  invoice_date, currency, total_amount, tax_amount, source ("upload"|"email"), file_path, file_hash,
  created_at

Rules:
- Deterministic parsing first. Add LLM only as fallback later.
- Docker-first: `docker compose up` should bring up everything.
- Keep it simple and testable. Add basic tests for API endpoints.

Non-goals for v0:
- Multi-tenant
- OAuth/Gmail ingestion
- n8n integration
- Advanced dashboards

