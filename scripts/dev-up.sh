#!/usr/bin/env bash
set -euo pipefail

echo "==> Pull latest code"
git pull

echo "==> Build + start containers"
docker compose up --build -d

echo "==> Health check (retrying)"
for i in {1..30}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    curl -fsS http://localhost:8000/health | cat
    echo
    echo "✅ dev-up done"
    exit 0
  fi
  sleep 1
done

echo "❌ API did not become healthy in time"
docker compose logs --tail=100 api
exit 1
