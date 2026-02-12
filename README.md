# InvoiceScope (self-hosted)

Developer convenience scripts are available in `scripts/`.

## Scripts

### Bring the stack up

```bash
./scripts/dev-up.sh
```

What it does:
- pulls the latest code (`git pull`)
- rebuilds and starts containers (`docker compose up --build -d`)
- checks API health (`GET /health`)

### Reset local environment

```bash
./scripts/dev-reset.sh
```

What it does:
- tears down containers and removes volumes (`docker compose down -v`)
- pulls latest code
- rebuilds and starts containers
- checks API health

### Smoke test invoice flow

```bash
./scripts/dev-smoke.sh [optional/path/to/invoice.pdf]
```

What it does:
- checks API health
- uploads an invoice PDF via `POST /invoices/upload`
- extracts the returned `id` with Python (no `jq` required)
- triggers parse via `POST /invoices/{id}/parse`
- fetches invoice list via `GET /invoices`

If no path is provided, it defaults to:
`/Users/ayub/Documents/Code/invoice-scope/docs/Invoice_SGIN26_10731.pdf`.
