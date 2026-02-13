# InvoiceScope (self-hosted)

Developer convenience scripts are available in `scripts/`.

## Scripts

### Bring the stack up

```bash
./scripts/dev-up.sh
```

What it does:
- stops containers (`docker compose down`)
- rebuilds and starts containers (`docker compose up --build -d`)

### Reset local environment

```bash
./scripts/dev-reset.sh
```

What it does:
- tears down containers and removes volumes (`docker compose down -v`)
- rebuilds and starts containers

## API and UI access

After `docker compose up --build`, the API is available at `http://localhost:8000`.

- Dashboard: `http://localhost:8000/dashboard`
- Invoice list UI: `http://localhost:8000/ui/invoices`
- Invoice detail UI: `http://localhost:8000/dashboard/invoices/{id}` (also available as `/ui/invoices/{id}`)

## Application version label

The invoice detail page shows an application version label sourced from `APP_VERSION`.

- Default: `2026.1`
- Override before build/run:

```bash
APP_VERSION=2026.2 ./scripts/dev-up.sh
```

### Dashboard upload/re-parse workflow

On the dashboard page:
- Uploading a PDF runs `POST /invoices/upload`, then automatically runs `POST /invoices/{id}/parse`.
- Parsing now applies deterministic vendor normalization (`AWS`, `Microsoft Azure`, `Freshdesk`) while preserving the original value in `vendor_raw`.
- Parsing now runs financial validation (currency format, non-negative totals/tax, and `tax <= total`). Invalid records are still stored and flagged with `needs_review=true` plus `validation_errors`.
- The page refreshes the monthly, MoM, anomaly, trend, and invoice list tables without reloading.
- A status message area shows success/error details (including duplicate `409` responses).
- Each invoice row has a **View** link and **Re-analyze** button. Detail pages include full extracted text and parsing metadata (`parsed_at`, `parser_version`, `source`, `file_hash`).

### New/updated invoice endpoints

- `GET /invoices/{id}/detail`: returns invoice fields + full `extracted_text` + metadata (`parsed_at`, `parser_version`, `source`, `file_hash`).
- `POST /invoices/{id}/parse`: reparses invoice, updates normalized vendor + `vendor_raw`, and refreshes validation state.

## Example curl commands

```bash
curl -s http://localhost:8000/health
curl -s "http://localhost:8000/reports/monthly?year=2026&month=1"
curl -s "http://localhost:8000/reports/anomalies?year=2026&month=1"
curl -s "http://localhost:8000/reports/trend?months=6"
```
