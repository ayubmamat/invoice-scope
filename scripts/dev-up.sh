#!/usr/bin/env bash
set -euo pipefail

echo "==> Pull latest code"
git pull

echo "==> Build + start containers"
docker compose up --build -d

echo "==> Health check"
healthy=0
for attempt in $(seq 1 30); do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done

if [ "$healthy" -ne 1 ]; then
  echo "❌ API did not become healthy after 30 seconds (http://localhost:8000/health)" >&2
  exit 1
fi

curl -fsS http://localhost:8000/health | cat
echo
echo "✅ dev-up done"
