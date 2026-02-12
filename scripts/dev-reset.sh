#!/usr/bin/env bash
set -euo pipefail

echo "⚠️  Resetting DB + volumes (docker compose down -v)"
docker compose down -v

echo "==> Pull latest code"
git pull

echo "==> Build + start containers"
docker compose up --build -d

echo "==> Health check"
curl -fsS http://localhost:8000/health | cat
echo
echo "✅ dev-reset done"
