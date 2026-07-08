"""Filing-chunk retrieval, one interface over two dialects (PLAN.md §8).

Postgres (the path the agent uses) runs `websearch_to_tsquery` + `ts_rank` + `ts_headline` against
the generated `filing_chunks.tsv`; SQLite (the unit-test dialect, which has no tsvector) falls back
to a token-AND `LIKE` so the same logic stays testable offline. The Postgres branch is exercised by
the Postgres integration job, not the SQLite unit gate — hence its `# pragma: no cover`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

_SNIPPET_BEFORE = 80
_SNIPPET_AFTER = 160
_SNIPPET_FALLBACK = 240


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


def search_chunks(
    session: Session,
    cik: int,
    query: str,
    *,
    item: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 8,
) -> list[ChunkHit]:
    """Top-`limit` chunks matching `query`, optionally filtered by item / fiscal_year."""
    if session.get_bind().dialect.name == "postgresql":
        return _search_pg(session, cik, query, item, fiscal_year, limit)  # pragma: no cover
    return _search_sqlite(session, cik, query, item, fiscal_year, limit)


def _search_sqlite(
    session: Session,
    cik: int,
    query: str,
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> list[ChunkHit]:
    tokens = query.split()
    if not tokens:  # no tokens -> no haystack (mirrors websearch on an empty query)
        return []
    # ESCAPE '\' + escaped tokens so a query's %/_ match literally, not as LIKE wildcards.
    clauses = " AND ".join(f"c.text LIKE :t{k} ESCAPE '\\'" for k in range(len(tokens)))
    params: dict[str, object] = {"cik": cik, "item": item, "fy": fiscal_year}
    for k, token in enumerate(tokens):
        params[f"t{k}"] = f"%{_like_escape(token)}%"
    sql = text(
        "SELECT c.accession AS accession, c.item AS item, c.fiscal_year AS fiscal_year, "
        "c.chunk_index AS chunk_index, c.text AS text, f.primary_doc_url AS url "
        "FROM filing_chunks c JOIN filings f ON f.accession = c.accession "
        f"WHERE c.cik = :cik AND {clauses} "
        "AND (:item IS NULL OR c.item = :item) "
        "AND (:fy IS NULL OR c.fiscal_year = :fy)"
    )
    lowered = [token.lower() for token in tokens]
    hits: list[ChunkHit] = []
    for row in session.execute(sql, params).mappings().all():
        chunk_text = str(row["text"])
        # Rank ≈ websearch relevance: total token occurrences (deterministic, explainable).
        rank = float(sum(chunk_text.lower().count(token) for token in lowered))
        hits.append(
            ChunkHit(
                accession=str(row["accession"]),
                item=str(row["item"]),
                fiscal_year=int(row["fiscal_year"]),
                chunk_index=int(row["chunk_index"]),
                snippet=_snippet(chunk_text, lowered),
                rank=rank,
                url=str(row["url"]),
            )
        )
    hits.sort(key=lambda h: (-h.rank, -h.fiscal_year, h.chunk_index))
    return hits[:limit]


def _like_escape(token: str) -> str:
    """Escape LIKE metacharacters so a token matches literally under ESCAPE '\\'."""
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(chunk_text: str, lowered_tokens: list[str]) -> str:
    low = chunk_text.lower()
    first = -1
    for token in lowered_tokens:
        idx = low.find(token)
        if idx != -1 and (first == -1 or idx < first):
            first = idx
    if first == -1:
        return " ".join(chunk_text.split())[:_SNIPPET_FALLBACK]
    start = max(0, first - _SNIPPET_BEFORE)
    end = min(len(chunk_text), first + _SNIPPET_AFTER)
    return " ".join(chunk_text[start:end].split())


def _search_pg(  # pragma: no cover — Postgres-only; covered by the integration job
    session: Session,
    cik: int,
    query: str,
    item: str | None,
    fiscal_year: int | None,
    limit: int,
) -> list[ChunkHit]:
    sql = text(
        "WITH q AS (SELECT websearch_to_tsquery('english', :query) AS tsq) "
        "SELECT c.accession AS accession, c.item AS item, c.fiscal_year AS fiscal_year, "
        "c.chunk_index AS chunk_index, "
        "ts_headline('english', c.text, q.tsq, "
        "'StartSel=**,StopSel=**,MaxFragments=2,MinWords=5,MaxWords=18') AS snippet, "
        "ts_rank(c.tsv, q.tsq) AS rank, f.primary_doc_url AS url "
        "FROM filing_chunks c JOIN filings f ON f.accession = c.accession CROSS JOIN q "
        "WHERE c.cik = :cik AND c.tsv @@ q.tsq "
        "AND (CAST(:item AS text) IS NULL OR c.item = CAST(:item AS text)) "
        "AND (CAST(:fy AS integer) IS NULL OR c.fiscal_year = CAST(:fy AS integer)) "
        "ORDER BY rank DESC, c.fiscal_year DESC, c.chunk_index ASC "
        "LIMIT :limit"
    )
    params = {"query": query, "cik": cik, "item": item, "fy": fiscal_year, "limit": limit}
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
