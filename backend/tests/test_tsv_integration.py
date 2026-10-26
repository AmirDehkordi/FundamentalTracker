"""Postgres-only checks for the dialect-guarded full-text column (db/models.py).

Marked integration: the SQLite unit suite (`pytest -m "not integration"`) skips these; they run
against the compose/CI Postgres, where the tsv generated column + GIN index actually exist. This is
the only automated coverage of P1's trickiest decision — the after_create tsv/GIN DDL.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tracker.db.models import Base


@pytest.mark.integration
def test_tsv_generated_column_and_gin_index_exist(pg_session: Session) -> None:
    has_column = pg_session.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'filing_chunks' AND column_name = 'tsv'"
        )
    ).scalar()
    assert has_column == 1

    has_index = pg_session.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_filing_chunks_tsv'")
    ).scalar()
    assert has_index == 1


@pytest.mark.integration
def test_full_text_search_hits_seeded_chunks(pg_session: Session) -> None:
    # mini_seed inserts 4 chunks all containing "supply constraints and demand"; the generated tsv
    # must index that text so websearch_to_tsquery finds them.
    count = pg_session.execute(
        text("SELECT count(*) FROM filing_chunks WHERE tsv @@ websearch_to_tsquery('english', :q)"),
        {"q": "supply constraints"},
    ).scalar()
    assert count == 4


@pytest.mark.integration
def test_create_all_is_idempotent_on_postgres(pg_session: Session) -> None:
    # Re-running create_all must not error: checkfirst skips existing tables, so the after_create
    # tsv/GIN DDL never refires and does not double-add the column or index.
    Base.metadata.create_all(pg_session.get_bind())
