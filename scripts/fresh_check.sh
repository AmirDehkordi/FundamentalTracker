#!/usr/bin/env bash
# Fresh-clone rehearsal (P10): prove `docker compose up` works from a bare clone using only the
# committed seed. Usage: scripts/fresh_check.sh [path-to-env-file]  (default: .env in repo root)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_SRC="${1:-$REPO_ROOT/.env}"
TMP_DIR="$(mktemp -d)"
CLONE_DIR="$TMP_DIR/repo"

cleanup() {
  if [ -d "$CLONE_DIR" ]; then
    (cd "$CLONE_DIR" && docker compose down -v >/dev/null 2>&1) || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> cloning $REPO_ROOT into $CLONE_DIR"
git clone --quiet "$REPO_ROOT" "$CLONE_DIR"
cp "$ENV_SRC" "$CLONE_DIR/.env"
cd "$CLONE_DIR"

echo "==> docker compose up -d --build"
docker compose up -d --build

echo "==> waiting for /health"
ok=0
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8000/health >/dev/null; then
    ok=1
    break
  fi
  sleep 2
done
if [ "$ok" -ne 1 ]; then
  echo "FAIL: /health never came up"
  exit 1
fi

echo "==> checking /api/companies"
count="$(curl -sf http://localhost:8000/api/companies | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
if [ "$count" != "5" ]; then
  echo "FAIL: expected 5 companies, got $count"
  exit 1
fi

echo "==> smoke test /api/ask"
if ! curl -sf -X POST http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is AAPL trailing P/E right now?", "history": []}' >/dev/null; then
  echo "FAIL: /api/ask smoke question failed"
  exit 1
fi

echo "PASS"
