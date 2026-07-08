#!/usr/bin/env bash
# Dump the dev Postgres to seed/init/01_seed.sql.gz, which docker-compose auto-restores on a fresh
# clone (./seed/init is mounted at /docker-entrypoint-initdb.d). Run after a live ingest.
# Usage: make seed-dump  (or: bash scripts/make_seed.sh)
set -euo pipefail

OUT="seed/init/01_seed.sql.gz"
mkdir -p seed/init

# -T disables the pseudo-TTY so the dump streams cleanly into the pipe.
docker compose exec -T db pg_dump -U tracker -d tracker | gzip >"$OUT"

# Sanity check: a real dump of the seeded universe is many KB; a near-empty file means the DB was
# empty or the dump failed silently. wc -c is portable (no macOS/Linux stat divergence).
bytes=$(wc -c <"$OUT")
if [ "$bytes" -lt 1024 ]; then
  echo "make_seed: $OUT is only ${bytes} bytes — DB empty or dump failed; aborting" >&2
  exit 1
fi
echo "make_seed: wrote $OUT (${bytes} bytes)"
