"""Filing-chunk retrieval — the SQLite ladder path (services/retrieval.py).

mini_seed gives AAPL FY2025 four Item 1A chunks, each "...supply constraints and demand." The
Postgres FTS path is covered separately in test_retrieval_integration.py. `search_chunks` returns a
`SearchResult(hits, mode)`; the three rungs (exact/relaxed/fuzzy) are each exercised here.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tracker.db.models import FilingChunk
from tracker.services import retrieval

AAPL_CIK = 320193
NVDA_CIK = 1045810
AAPL_2025 = "0000320193-2025-10K"


# --- sanitisation (pure, no DB) -----------------------------------------------------------------


def test_sanitize_drops_stopwords_and_short_tokens() -> None:
    # The exact sentence that broke the flagship search collapses to its content keywords.
    assert retrieval.sanitize_query(
        "what are the main themes in the results of operations revenue gross margin data center "
        "gaming"
    ) == ["revenue", "gross", "margin", "data", "center", "gaming"]


def test_sanitize_strips_punctuation_and_dedupes() -> None:
    assert retrieval.sanitize_query("Supply-chain: supply, SUPPLY constraints!") == [
        "supply",
        "chain",
        "constraints",
    ]


def test_sanitize_caps_at_six_terms() -> None:
    assert len(retrieval.sanitize_query("alpha bravo charlie delta echo foxtrot golf hotel")) == 6


def test_sanitize_empty() -> None:
    assert retrieval.sanitize_query("") == []
    assert retrieval.sanitize_query("the of a an to") == []  # all stopwords


# --- rung 1: exact (whole-word AND) -------------------------------------------------------------


def test_search_matches_query_exact(db_session: Session) -> None:
    result = retrieval.search_chunks(db_session, AAPL_CIK, "supply constraints")
    assert result.mode == "exact"
    assert len(result.hits) == 4
    for hit in result.hits:
        assert hit.item == "1A"
        assert hit.fiscal_year == 2025
        assert hit.accession == AAPL_2025
        assert hit.url.endswith(f"{AAPL_2025}.htm")
        assert hit.snippet
        assert hit.rank >= 1


def test_search_multi_token_and(db_session: Session) -> None:
    # A chunk with only "supply" (no "demand") must be excluded by the AND of "supply demand" —
    # this distinguishes the exact rung from a relaxed OR (PLAN §8).
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
    both = retrieval.search_chunks(db_session, AAPL_CIK, "supply demand")
    assert both.mode == "exact"
    assert len(both.hits) == 4  # the supply-only chunk is excluded by AND semantics
    assert all(hit.chunk_index != 9 for hit in both.hits)
    single = retrieval.search_chunks(db_session, AAPL_CIK, "supply")
    assert len(single.hits) == 5  # a single token matches the supply-only chunk too


def test_search_item_filter(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, AAPL_CIK, "supply", item="7").hits == []
    assert len(retrieval.search_chunks(db_session, AAPL_CIK, "supply", item="1A").hits) == 4


def test_search_fiscal_year_filter(db_session: Session) -> None:
    assert len(retrieval.search_chunks(db_session, AAPL_CIK, "supply", fiscal_year=2025).hits) == 4
    assert retrieval.search_chunks(db_session, AAPL_CIK, "supply", fiscal_year=2024).hits == []


def test_search_limit_and_order(db_session: Session) -> None:
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply", limit=2).hits
    assert len(hits) == 2
    assert [h.chunk_index for h in hits] == [0, 1]  # equal rank -> chunk_index ascending


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
    hits = retrieval.search_chunks(db_session, AAPL_CIK, "supply").hits
    assert hits[0].chunk_index == 4  # three occurrences -> highest rank


# --- rung 2: relaxed (whole-word OR) ------------------------------------------------------------


def test_search_relaxed_mode(db_session: Session) -> None:
    # "cryptocurrency" appears nowhere; "supply" does. Strict AND finds nothing, OR relaxes to the
    # supply chunks — the fix for the AND-semantics miss. `matched_mode` reports the relaxation.
    result = retrieval.search_chunks(db_session, AAPL_CIK, "supply cryptocurrency")
    assert result.mode == "relaxed"
    assert len(result.hits) == 4


# --- rung 3: fuzzy (substring on the rarest) ----------------------------------------------------


def test_search_fuzzy_mode(db_session: Session) -> None:
    # "constraint" (singular) is no chunk's whole word (they say "constraints"), so exact and
    # relaxed both miss; the fuzzy rung substring-matches the rarest term.
    result = retrieval.search_chunks(db_session, AAPL_CIK, "constraint")
    assert result.mode == "fuzzy"
    assert len(result.hits) == 4


# --- no match / scoping / empty -----------------------------------------------------------------


def test_search_no_match(db_session: Session) -> None:
    result = retrieval.search_chunks(db_session, AAPL_CIK, "cryptocurrency mining")
    assert result.mode == "none" and result.hits == []


def test_search_cik_scoping(db_session: Session) -> None:
    result = retrieval.search_chunks(db_session, NVDA_CIK, "supply")  # NVDA has no chunks
    assert result.mode == "none" and result.hits == []


def test_search_empty_query(db_session: Session) -> None:
    assert retrieval.search_chunks(db_session, AAPL_CIK, "").hits == []
    assert retrieval.search_chunks(db_session, AAPL_CIK, "   ").mode == "none"


def test_snippet_fallback_when_token_absent() -> None:
    # Defensive branch: a token not present -> the leading-text fallback snippet.
    snippet = retrieval._snippet("Some risk-factor text without the term.", ["zzz"])
    assert snippet == "Some risk-factor text without the term."
