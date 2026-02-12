#!/usr/bin/env bash
set -euo pipefail

echo "==> Pull latest code"
git pull

echo "==> Build + start containers"
docker compose up --build -d

echo "==> Health check"
curl -fsS http://localhost:8000/health | cat
echo
echo "✅ dev-up done"
