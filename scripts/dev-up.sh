#!/usr/bin/env bash
set -euo pipefail

echo "==> Stop containers"
docker compose down

echo "==> Rebuild + start containers"
docker compose up --build -d

echo "✅ dev-up done"
