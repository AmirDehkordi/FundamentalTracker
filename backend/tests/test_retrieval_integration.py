"""Postgres FTS path for retrieval (services/retrieval._search_pg) — the path the agent uses.

Marked integration: the SQLite unit gate skips these; they run against the compose/CI Postgres where
the generated tsv column + GIN index exist. mini_seed gives AAPL FY2025 four Item 1A chunks all
containing "supply constraints and demand".
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from tracker.db.models import FilingChunk
from tracker.services import retrieval

AAPL_CIK = 320193
AAPL_2025 = "0000320193-2025-10K"


@pytest.mark.integration
def test_search_pg_ranks_and_highlights(pg_session: Session) -> None:
    hits = retrieval.search_chunks(pg_session, AAPL_CIK, "supply constraints").hits
    assert len(hits) == 4
    assert all(hit.rank > 0 for hit in hits)
    assert all(hit.accession == AAPL_2025 for hit in hits)
    assert any("**" in hit.snippet for hit in hits)  # ts_headline markers
    ranks = [hit.rank for hit in hits]
    assert ranks == sorted(ranks, reverse=True)


@pytest.mark.integration
def test_search_pg_item_and_year_filters(pg_session: Session) -> None:
    assert retrieval.search_chunks(pg_session, AAPL_CIK, "supply", item="7").hits == []
    assert retrieval.search_chunks(pg_session, AAPL_CIK, "supply", fiscal_year=2024).hits == []
    assert len(retrieval.search_chunks(pg_session, AAPL_CIK, "supply", fiscal_year=2025).hits) == 4


@pytest.mark.integration
def test_search_pg_paraphrase_returns_zero(pg_session: Session) -> None:
    # websearch_to_tsquery ANDs terms; a paraphrase with no shared lexemes finds nothing (§8).
    assert retrieval.search_chunks(pg_session, AAPL_CIK, "capacity limitations").hits == []


@pytest.mark.integration
def test_search_pg_quoted_phrase(pg_session: Session) -> None:
    assert len(retrieval.search_chunks(pg_session, AAPL_CIK, '"supply constraints"').hits) == 4


@pytest.mark.integration
def test_search_pg_limit(pg_session: Session) -> None:
    assert len(retrieval.search_chunks(pg_session, AAPL_CIK, "supply", limit=2).hits) == 2


@pytest.mark.integration
def test_search_pg_rank_orders_by_relevance(pg_session: Session) -> None:
    # A chunk repeating the term must outrank the single-occurrence seed chunks, so ts_rank is not
    # tied and the descending-order guarantee is actually exercised.
    pg_session.add(
        FilingChunk(
            accession=AAPL_2025,
            cik=AAPL_CIK,
            item="1A",
            fiscal_year=2025,
            chunk_index=99,
            text="supply supply supply supply chain risks",
        )
    )
    pg_session.commit()
    hits = retrieval.search_chunks(pg_session, AAPL_CIK, "supply").hits
    assert hits[0].chunk_index == 99  # most occurrences -> strictly highest ts_rank
    assert hits[0].rank > hits[-1].rank
