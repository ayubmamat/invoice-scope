#!/usr/bin/env bash
set -euo pipefail

echo "⚠️  Resetting DB + volumes (docker compose down -v)"
docker compose down -v

echo "==> Rebuild + start containers"
docker compose up --build -d

echo "✅ dev-reset done"
