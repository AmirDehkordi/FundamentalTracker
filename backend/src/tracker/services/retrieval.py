"""Filing-chunk retrieval, one interface over two dialects (PLAN.md §8).

The honest failure mode of lexical FTS is AND-semantics: a whole-sentence query ANDs every term and
returns nothing. Rather than let the agent apologise, `search_chunks` runs a **retry ladder** and
reports which rung matched so the trace can show "relaxed search":

  1. exact   — strict AND (Postgres `websearch_to_tsquery`; SQLite whole-word AND)
  2. relaxed — OR of the sanitised keywords (Postgres `to_tsquery('a | b')`; SQLite whole-word OR)
  3. fuzzy   — substring match on the 2 rarest keywords (Postgres `ILIKE`; SQLite substring),
               catching stemmed/compound forms the lexer split away

Input is sanitised first (lowercase, strip punctuation, drop stopwords, cap ~6 terms) so a sentence
degrades to its content words. The SQLite path mirrors the three rungs so each is unit-testable
offline; the real Postgres SQL is exercised by the integration job — hence its `# pragma: no cover`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import TextClause, text
from sqlalchemy.orm import Session

_SNIPPET_BEFORE = 80
_SNIPPET_AFTER = 160
_SNIPPET_FALLBACK = 240
_MAX_TERMS = 6  # cap sanitised keywords so a long sentence can't AND itself to zero
_MIN_TERM_LEN = 3  # single letters / initials ("p", "e") carry no retrieval signal

SearchMode = Literal["exact", "relaxed", "fuzzy", "none"]

# English function words + a few filing-navigation words ("results of operations", "main themes")
# that inflate a query without narrowing it. Deliberately conservative — real content words
# (revenue, margin, data, gaming, …) are never listed.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "their",
        "our",
        "we",
        "us",
        "you",
        "your",
        "they",
        "them",
        "he",
        "she",
        "his",
        "her",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "about",
        "into",
        "over",
        "under",
        "than",
        "then",
        "there",
        "here",
        "some",
        "any",
        "all",
        "each",
        "per",
        "vs",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "not",
        "no",
        "but",
        "if",
        "so",
        "up",
        "out",
        "off",
        # filing-navigation noise
        "main",
        "top",
        "key",
        "themes",
        "theme",
        "overview",
        "results",
        "operations",
        "discussion",
        "analysis",
        "section",
        "item",
        "please",
        "list",
        "tell",
        "give",
    }
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """One retrieval hit: snippet + provenance (item, FY, accession, SEC URL) for a citation."""

    accession: str
    item: str
    fiscal_year: int
    chunk_index: int
    snippet: str
    rank: float
    url: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Hits + the ladder rung that produced them, so the tool/trace can say "relaxed search"."""

    hits: list[ChunkHit]
    mode: SearchMode


def sanitize_query(query: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords + <3-char tokens, dedupe (order-kept),
    cap at `_MAX_TERMS`. A whole sentence degrades to its distinctive content words."""
    seen: dict[str, None] = {}
    for raw in _TOKEN_SPLIT.split(query.lower()):
        if len(raw) >= _MIN_TERM_LEN and raw not in _STOPWORDS:
            seen.setdefault(raw, None)
        if len(seen) >= _MAX_TERMS:
            break
    return list(seen)


def search_chunks(
    session: Session,
    cik: int,
    query: str,
    *,
    item: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 8,
) -> SearchResult:
    """Top-`limit` chunks matching `query` via the retry ladder, optionally filtered by item / FY.

    Returns the hits AND the rung (`exact`/`relaxed`/`fuzzy`/`none`) that produced them."""
    tokens = sanitize_query(query)
    if session.get_bind().dialect.name == "postgresql":
        return _search_pg(session, cik, query, tokens, item, fiscal_year, limit)  # pragma: no cover
    return _search_sqlite(session, cik, tokens, item, fiscal_year, limit)


# ---------------------------------------------------------------------------
# SQLite path (the unit-test dialect) — the ladder mirrored in Python
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Doc:
    hit_base: tuple[str, str, int, int, str]  # accession, item, fiscal_year, chunk_index, url
    text: str
    lowered: str
    words: frozenset[str]


def _search_sqlite(
    session: Session,
    cik: int,
    tokens: list[str],
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> SearchResult:
    if not tokens:
        return SearchResult([], "none")
    docs = _load_docs(session, cik, item, fiscal_year)
    if not docs:
        return SearchResult([], "none")

    # Rung 1 — exact: every token present as a whole word (mirrors tsquery AND on lexemes).
    hits = _rank_docs(docs, tokens, lambda d, ts: all(t in d.words for t in ts))
    if hits:
        return SearchResult(hits[:limit], "exact")

    # Rung 2 — relaxed: any token present as a whole word (mirrors OR-relaxed to_tsquery).
    hits = _rank_docs(docs, tokens, lambda d, ts: any(t in d.words for t in ts))
    if hits:
        return SearchResult(hits[:limit], "relaxed")

    # Rung 3 — fuzzy: the 2 rarest tokens as raw substrings (mirrors ILIKE) — catches stemmed /
    # compound forms the whole-word rungs split away (e.g. "supply" inside "supplies").
    rarest = _rarest_terms(docs, tokens, 2)
    hits = _rank_docs(docs, rarest, lambda d, ts: any(t in d.lowered for t in ts))
    if hits:
        return SearchResult(hits[:limit], "fuzzy")

    return SearchResult([], "none")


def _load_docs(session: Session, cik: int, item: str | None, fiscal_year: int | None) -> list[_Doc]:
    sql = text(
        "SELECT c.accession AS accession, c.item AS item, c.fiscal_year AS fiscal_year, "
        "c.chunk_index AS chunk_index, c.text AS text, f.primary_doc_url AS url "
        "FROM filing_chunks c JOIN filings f ON f.accession = c.accession "
        "WHERE c.cik = :cik "
        "AND (:item IS NULL OR c.item = :item) "
        "AND (:fy IS NULL OR c.fiscal_year = :fy)"
    )
    params = {"cik": cik, "item": item, "fy": fiscal_year}
    docs: list[_Doc] = []
    for row in session.execute(sql, params).mappings().all():
        chunk_text = str(row["text"])
        lowered = chunk_text.lower()
        docs.append(
            _Doc(
                hit_base=(
                    str(row["accession"]),
                    str(row["item"]),
                    int(row["fiscal_year"]),
                    int(row["chunk_index"]),
                    str(row["url"]),
                ),
                text=chunk_text,
                lowered=lowered,
                words=frozenset(_TOKEN_SPLIT.split(lowered)),
            )
        )
    return docs


def _rarest_terms(docs: list[_Doc], tokens: list[str], n: int) -> list[str]:
    """The `n` lowest-document-frequency tokens (ties broken toward longer, more specific terms)."""
    df = {t: sum(1 for d in docs if t in d.lowered) for t in tokens}
    return sorted(tokens, key=lambda t: (df[t], -len(t)))[:n]


def _rank_docs(
    docs: list[_Doc],
    tokens: list[str],
    matches: Callable[[_Doc, list[str]], bool],
) -> list[ChunkHit]:
    hits: list[ChunkHit] = []
    for d in docs:
        if not matches(d, tokens):
            continue
        # Rank ≈ relevance: total token occurrences (deterministic, explainable).
        rank = float(sum(d.lowered.count(t) for t in tokens))
        accession, item, fiscal_year, chunk_index, url = d.hit_base
        hits.append(
            ChunkHit(
                accession=accession,
                item=item,
                fiscal_year=fiscal_year,
                chunk_index=chunk_index,
                snippet=_snippet(d.text, tokens),
                rank=rank,
                url=url,
            )
        )
    hits.sort(key=lambda h: (-h.rank, -h.fiscal_year, h.chunk_index))
    return hits


def _snippet(chunk_text: str, tokens: list[str]) -> str:
    low = chunk_text.lower()
    first = -1
    for token in tokens:
        idx = low.find(token)
        if idx != -1 and (first == -1 or idx < first):
            first = idx
    if first == -1:
        return " ".join(chunk_text.split())[:_SNIPPET_FALLBACK]
    start = max(0, first - _SNIPPET_BEFORE)
    end = min(len(chunk_text), first + _SNIPPET_AFTER)
    return " ".join(chunk_text[start:end].split())


def _like_escape(token: str) -> str:
    """Escape LIKE/ILIKE metacharacters so a token matches literally under ESCAPE '\\'."""
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Postgres path (the path the agent uses) — covered by the integration job
# ---------------------------------------------------------------------------

_PG_SELECT = (
    "SELECT c.accession AS accession, c.item AS item, c.fiscal_year AS fiscal_year, "
    "c.chunk_index AS chunk_index, "
    "ts_headline('english', c.text, {tsq}, "
    "'StartSel=**,StopSel=**,MaxFragments=2,MinWords=5,MaxWords=18') AS snippet, "
    "{rank} AS rank, f.primary_doc_url AS url "
    "FROM filing_chunks c JOIN filings f ON f.accession = c.accession {cross} "
    "WHERE c.cik = :cik AND {match} "
    "AND (CAST(:item AS text) IS NULL OR c.item = CAST(:item AS text)) "
    "AND (CAST(:fy AS integer) IS NULL OR c.fiscal_year = CAST(:fy AS integer)) "
    "ORDER BY rank DESC, c.fiscal_year DESC, c.chunk_index ASC LIMIT :limit"
)


def _search_pg(  # pragma: no cover — Postgres-only; covered by the integration job
    session: Session,
    cik: int,
    raw_query: str,
    tokens: list[str],
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> SearchResult:
    # Rung 1 — exact: websearch_to_tsquery as given (its own parser handles stopwords/quotes).
    hits = _pg_tsquery(
        session, cik, "websearch_to_tsquery('english', :query)", raw_query, item, fiscal_year, limit
    )
    if hits:
        return SearchResult(hits, "exact")
    if not tokens:
        return SearchResult([], "none")

    # Rung 2 — relaxed: OR the sanitised keywords via to_tsquery('a | b | …').
    or_expr = " | ".join(tokens)
    hits = _pg_tsquery(
        session, cik, "to_tsquery('english', :query)", or_expr, item, fiscal_year, limit
    )
    if hits:
        return SearchResult(hits, "relaxed")

    # Rung 3 — fuzzy: ILIKE on the 2 rarest keywords (substring; catches lexer-split compounds).
    hits = _pg_ilike(session, cik, _pg_rarest(session, cik, tokens, 2), item, fiscal_year, limit)
    if hits:
        return SearchResult(hits, "fuzzy")
    return SearchResult([], "none")


def _pg_tsquery(  # pragma: no cover
    session: Session,
    cik: int,
    tsq_fn: str,
    query: str,
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> list[ChunkHit]:
    sql = text(
        "WITH q AS (SELECT "
        + tsq_fn
        + " AS tsq) "
        + _PG_SELECT.format(
            tsq="q.tsq", rank="ts_rank(c.tsv, q.tsq)", cross="CROSS JOIN q", match="c.tsv @@ q.tsq"
        )
    )
    params = {"query": query, "cik": cik, "item": item, "fy": fiscal_year, "limit": limit}
    return _pg_rows(session, sql, params)


def _pg_ilike(  # pragma: no cover
    session: Session,
    cik: int,
    terms: list[str],
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> list[ChunkHit]:
    if not terms:
        return []
    ors = " OR ".join(f"c.text ILIKE :t{k} ESCAPE '\\'" for k in range(len(terms)))
    # No tsquery here, so ts_headline gets an empty query and falls back to a plain head fragment.
    sql = text(
        _PG_SELECT.format(
            tsq="plainto_tsquery('english', '')", rank="0.0", cross="", match=f"({ors})"
        )
    )
    params: dict[str, object] = {"cik": cik, "item": item, "fy": fiscal_year, "limit": limit}
    for k, term in enumerate(terms):
        params[f"t{k}"] = f"%{_like_escape(term)}%"
    return _pg_rows(session, sql, params)


def _pg_rarest(  # pragma: no cover
    session: Session, cik: int, tokens: list[str], n: int
) -> list[str]:
    df: dict[str, int] = {}
    for token in tokens:
        count = session.scalar(
            text(
                "SELECT count(*) FROM filing_chunks WHERE cik = :cik AND text ILIKE :t ESCAPE '\\'"
            ),
            {"cik": cik, "t": f"%{_like_escape(token)}%"},
        )
        df[token] = int(count or 0)
    return sorted(tokens, key=lambda t: (df[t], -len(t)))[:n]


def _pg_rows(  # pragma: no cover
    session: Session, sql: TextClause, params: dict[str, Any]
) -> list[ChunkHit]:
    return [
        ChunkHit(
            accession=str(row["accession"]),
            item=str(row["item"]),
            fiscal_year=int(row["fiscal_year"]),
            chunk_index=int(row["chunk_index"]),
            snippet=str(row["snippet"]),
            rank=float(row["rank"]),
            url=str(row["url"]),
        )
        for row in session.execute(sql, params).mappings().all()
    ]
