"""Idempotent schema bootstrap: create every table against DATABASE_URL.

Re-runnable: metadata.create_all(checkfirst=True) skips tables that already exist, so the
Postgres-only tsv/GIN after_create DDL (see db/models.py) fires only on a table's first creation;
those statements also carry IF NOT EXISTS. Requires the `tracker` package to be installed (uv sync).
"""

from __future__ import annotations

# Importing Base pulls in models.py, where ALL six tables register on Base.metadata.
from tracker.db.models import Base
from tracker.db.session import get_engine


def main() -> None:
    Base.metadata.create_all(get_engine())


if __name__ == "__main__":
    main()
