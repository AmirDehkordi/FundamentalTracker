"""Filing-chunk retrieval — the SQLite ILIKE fallback path (services/retrieval.py).

mini_seed gives AAPL FY2025 four Item 1A chunks, each "...supply constraints and demand." The
Postgres FTS path is covered separately in test_retrieval_integration.py.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tracker.db.models import FilingChunk
from tracker.services import retrieval

AAPL_CIK = 320193
NVDA_CIK = 1045810
AAPL_2025 = "0000320193-2025-10K"


def test_search_matches_query(db_session: Session) -> None:
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply constraints")
    assert len(hits) == 4
    for hit in hits:
        assert hit.item == "1A"
        assert hit.fiscal_year == 2025
        assert hit.accession == AAPL_2025
        assert hit.url.endswith(f"{AAPL_2025}.htm")
        assert hit.snippet
        assert hit.rank >= 1


def test_search_multi_token_and(db_session: Session) -> None:
    # A chunk with only "supply" (no "demand") must be excluded by the AND of "supply demand" —
    # this is what distinguishes the token-AND fallback from a token-OR regression (PLAN §8).
    db_session.add(
        FilingChunk(
            accession=AAPL_2025,
            cik=AAPL_CIK,
            item="1A",
            fiscal_year=2025,
            chunk_index=9,
            text="Only supply is discussed in this paragraph, nothing further.",
        )
    )
    db_session.commit()
    assert len(retrieval.search_chunks(db_session, AAPL_CIK, "supply")) == 5  # OR-ish single token
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply demand")
    assert len(hits) == 4  # the supply-only chunk is excluded by AND semantics
    assert all(hit.chunk_index != 9 for hit in hits)


def test_search_like_metacharacters_are_literal(db_session: Session) -> None:
    # '%' is a literal, not a SQL wildcard: no chunk contains 'constraints%demand' (each says
    # "constraints and demand"), so an escaped LIKE returns nothing (unescaped would match 4).
    assert retrieval.search_chunks(db_session, AAPL_CIK, "constraints%demand") == []


def test_search_item_filter(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, AAPL_CIK, "supply", item="7") == []
    assert len(retrieval.search_chunks(db_session, AAPL_CIK, "supply", item="1A")) == 4


def test_search_fiscal_year_filter(db_session: Session) -> None:
    assert len(retrieval.search_chunks(db_session, AAPL_CIK, "supply", fiscal_year=2025)) == 4
    assert retrieval.search_chunks(db_session, AAPL_CIK, "supply", fiscal_year=2024) == []


def test_search_limit_and_order(db_session: Session) -> None:
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply", limit=2)
    assert len(hits) == 2
    assert [h.chunk_index for h in hits] == [0, 1]  # equal rank -> chunk_index ascending


def test_search_no_match(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, AAPL_CIK, "cryptocurrency mining") == []


def test_search_cik_scoping(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, NVDA_CIK, "supply") == []  # NVDA has no chunks


def test_search_empty_query(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, AAPL_CIK, "") == []
    assert retrieval.search_chunks(db_session, AAPL_CIK, "   ") == []


def test_search_rank_orders_by_occurrences(db_session: Session) -> None:
    db_session.add(
        FilingChunk(
            accession=AAPL_2025,
            cik=AAPL_CIK,
            item="1A",
            fiscal_year=2025,
            chunk_index=4,
            text="supply supply supply chain scrutiny.",
        )
    )
    db_session.commit()
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply")
    assert hits[0].chunk_index == 4  # three occurrences -> highest rank


def test_snippet_fallback_when_token_absent() -> None:
    # Defensive branch: a token not present -> the leading-text fallback snippet.
    snippet = retrieval._snippet("Some risk-factor text without the term.", ["zzz"])
    assert snippet == "Some risk-factor text without the term."
