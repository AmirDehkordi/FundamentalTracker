"""Shared fixtures. Unit fixtures use SQLite in-memory (no Postgres); the integration fixture is
skipped unless TEST_DATABASE_URL points at a Postgres."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from fixtures.mini_seed import seed_minimal
from tracker.db.models import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    """SQLite in-memory, seeded. StaticPool + one shared connection keeps data alive per test.

    The tsv/GIN DDL is dialect-guarded, so create_all is a no-op for it here; the base filing_chunks
    table is created normally and mini_seed inserts chunk rows without a tsv value.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_minimal(session)
        yield session
    engine.dispose()


@pytest.fixture
def pg_session() -> Iterator[Session]:
    """Postgres-backed session for @pytest.mark.integration tests. Here the tsv column + GIN index
    ARE created (the after_create DDL fires on the postgresql dialect).

    TEST_DATABASE_URL MUST point at a DISPOSABLE database: this drops and recreates the whole schema
    per test, so the tsv/GIN after_create DDL is re-exercised and repeated seeds never collide on a
    persistent server. CI uses an ephemeral service db; locally use a throwaway (e.g. tracker_test),
    never the seed db.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            seed_minimal(session)
            yield session
    finally:
        engine.dispose()
