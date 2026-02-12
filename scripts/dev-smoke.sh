#!/usr/bin/env bash
set -euo pipefail

PDF_PATH="${1:-/Users/ayub/Documents/Code/invoice-scope/docs/Invoice_SGIN26_10731.pdf}"

echo "==> Health check"
curl -fsS http://localhost:8000/health | cat
echo

echo "==> Uploading sample invoice: $PDF_PATH"
RESP="$(curl -fsS -F "file=@${PDF_PATH}" http://localhost:8000/invoices/upload)"
echo "$RESP"

# extract id (no jq dependency)
ID="$(echo "$RESP" | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')"

echo "==> Re-parse invoice id=$ID"
curl -fsS -X POST "http://localhost:8000/invoices/${ID}/parse" | cat
echo

echo "==> List invoices"
curl -fsS http://localhost:8000/invoices | cat
echo

echo "✅ dev-smoke done"
