"""XBRL ingestion runner: resolve the universe, pull company-facts, upsert, print a spot-check.

Postgres in production (ON CONFLICT ... DO UPDATE on the natural key); the same
on_conflict_do_update runs on SQLite so the upsert path is unit-tested without a database service
(fiscal.py sets the dialect-portable precedent). Per the CLAUDE.md error policy a single company
failing is logged and skipped — never a crashed run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tracker.config import get_settings
from tracker.db.models import Company, Filing, FilingChunk, Fundamental, InsiderTransaction, Price
from tracker.db.session import session_scope
from tracker.ingestion import edgar_client, filings, form4, prices, submissions, xbrl
from tracker.ingestion.xbrl import FundamentalFact
from tracker.services.fiscal import format_fy_label

logger = logging.getLogger(__name__)

# Fundamental columns refreshed on conflict — everything except the natural key and surrogate id.
_UPDATE_COLS = (
    "source_tag",
    "period_start",
    "value",
    "unit",
    "accession",
    "filed",
    "form",
    "superseded_value",
    "superseded_filed",
)


@dataclass(frozen=True)
class CompanySummary:
    """Per-company spot-check row so a reviewer can verify against the real 10-K in 30 seconds."""

    ticker: str
    cik: int
    fiscal_years: int
    latest_fy: int | None
    latest_period_end: date | None
    latest_revenue: Decimal | None
    latest_accession: str | None

    @property
    def latest_fy_label(self) -> str:
        """FY label with its ended-date, per CLAUDE.md ("FY2026 (ended 2026-01-25)")."""
        if self.latest_fy is None or self.latest_period_end is None:
            return "-"
        return format_fy_label(self.latest_fy, self.latest_period_end)

    @property
    def accession_url(self) -> str:
        if self.latest_accession is None:
            return "-"
        nodash = self.latest_accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{nodash}/"


def _insert(session: Session) -> Any:
    """Dialect-specific INSERT ... ON CONFLICT: Postgres in prod, SQLite in the unit suite."""
    return pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert


def _upsert_company(session: Session, cik: int, ticker: str, name: str) -> None:
    stmt = _insert(session)(Company).values(cik=cik, ticker=ticker, name=name)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Company.cik], set_={"ticker": ticker, "name": name}
    )
    session.execute(stmt)


def _upsert_fundamentals(session: Session, facts: list[FundamentalFact]) -> None:
    if not facts:
        return
    stmt = _insert(session)(Fundamental).values([f.model_dump() for f in facts])
    stmt = stmt.on_conflict_do_update(
        index_elements=["cik", "concept", "fiscal_year", "period_end"],
        set_={col: getattr(stmt.excluded, col) for col in _UPDATE_COLS},
    )
    session.execute(stmt)


def _summarize(ticker: str, cik: int, facts: list[FundamentalFact]) -> CompanySummary:
    revenue = sorted((f for f in facts if f.concept == "revenue"), key=lambda f: f.fiscal_year)
    years = {f.fiscal_year for f in facts}
    latest = revenue[-1] if revenue else None
    return CompanySummary(
        ticker=ticker,
        cik=cik,
        fiscal_years=len(years),
        latest_fy=latest.fiscal_year if latest else (max(years) if years else None),
        latest_period_end=latest.period_end if latest else None,
        latest_revenue=latest.value if latest else None,
        latest_accession=latest.accession if latest else None,
    )


def run_xbrl(from_cache: bool = False) -> list[CompanySummary]:
    """Ingest annual fundamentals for the configured universe; return per-company summaries."""
    edgar_client.from_cache = from_cache
    tickers = get_settings().universe_tickers
    ticker_map = xbrl.load_ticker_map(tickers)

    summaries: list[CompanySummary] = []
    with session_scope() as session:
        for ticker in tickers:
            resolved = ticker_map.get(ticker)
            if resolved is None:
                continue  # missing ticker already warned by load_ticker_map
            cik, name = resolved
            try:
                facts = xbrl.extract_annual_facts(xbrl.fetch_companyfacts(cik))
                # Savepoint per company: on Postgres the first failed execute aborts the WHOLE
                # transaction, so without this a single bad filer would crash the run and discard
                # the companies already ingested. begin_nested rolls back just this company.
                with session.begin_nested():
                    _upsert_company(session, cik, ticker, name)
                    _upsert_fundamentals(session, facts)
                summaries.append(_summarize(ticker, cik, facts))
            except Exception:
                logger.exception("xbrl ingest failed for %s (cik=%d); skipping", ticker, cik)
    return summaries


def print_summary(summaries: list[CompanySummary]) -> None:
    """Print the per-company spot-check table to stdout."""
    header = f"{'TICKER':<7}{'FYs':>4}  {'LATEST FY':<26}{'LATEST REVENUE':>20}  ACCESSION URL"
    print(header)
    print("-" * len(header))
    for s in sorted(summaries, key=lambda s: s.ticker):
        revenue = f"{s.latest_revenue:,.0f}" if s.latest_revenue is not None else "-"
        print(
            f"{s.ticker:<7}{s.fiscal_years:>4}  {s.latest_fy_label:<26}"
            f"{revenue:>20}  {s.accession_url}"
        )


# --------------------------------------------------------------------------------------------------
# Filings lane (10-K narrative chunks)
# --------------------------------------------------------------------------------------------------

_FILING_UPDATE_COLS = ("cik", "form", "fiscal_year", "period_end", "filed", "primary_doc_url")


@dataclass(frozen=True)
class FilingSummary:
    """Per-company chunk counts by (item, fiscal_year) so a reviewer can eyeball coverage."""

    ticker: str
    cik: int
    chunk_counts: tuple[tuple[str, int, int], ...]  # sorted (item, fiscal_year, count)


def _upsert_filings(session: Session, rows: list[filings.FilingRow]) -> None:
    if not rows:
        return
    stmt = _insert(session)(Filing).values([r.model_dump() for r in rows])
    stmt = stmt.on_conflict_do_update(
        index_elements=["accession"],
        set_={col: getattr(stmt.excluded, col) for col in _FILING_UPDATE_COLS},
    )
    session.execute(stmt)


def _replace_filing_chunks(session: Session, rows: list[filings.ChunkRow]) -> None:
    """Delete existing (accession, item) chunks then insert.

    A re-ingest yielding FEWER chunks must not leave orphaned high-index rows, which a pure upsert
    on the (accession, item, chunk_index) natural key would.
    """
    if not rows:
        return
    for accession, item in {(r.accession, r.item) for r in rows}:
        session.execute(
            delete(FilingChunk).where(FilingChunk.accession == accession, FilingChunk.item == item)
        )
    stmt = _insert(session)(FilingChunk).values([r.model_dump() for r in rows])
    # After the delete there is no conflict; do-nothing only guards a same-batch key repeat.
    stmt = stmt.on_conflict_do_nothing(index_elements=["accession", "item", "chunk_index"])
    session.execute(stmt)


def _summarize_filings(ticker: str, cik: int, rows: list[filings.ChunkRow]) -> FilingSummary:
    counts: dict[tuple[str, int], int] = {}
    for r in rows:
        counts[(r.item, r.fiscal_year)] = counts.get((r.item, r.fiscal_year), 0) + 1
    ordered = tuple(sorted((item, fy, c) for (item, fy), c in counts.items()))
    return FilingSummary(ticker=ticker, cik=cik, chunk_counts=ordered)


def run_filings(from_cache: bool = False) -> list[FilingSummary]:
    """Ingest the two most recent 10-Ks' Item 1A/7 chunks for the universe; return summaries."""
    edgar_client.from_cache = from_cache
    tickers = get_settings().universe_tickers
    ticker_map = xbrl.load_ticker_map(tickers)

    summaries: list[FilingSummary] = []
    with session_scope() as session:
        for ticker in tickers:
            resolved = ticker_map.get(ticker)
            if resolved is None:
                continue  # missing ticker already warned by load_ticker_map
            cik, name = resolved
            try:
                records = submissions.recent_filings(submissions.fetch(cik))
                filing_rows, chunk_rows = filings.build_filing_chunks(cik, ticker, records)
                with session.begin_nested():  # savepoint per company (see run_xbrl)
                    _upsert_company(session, cik, ticker, name)
                    _upsert_filings(session, filing_rows)  # parent rows before chunks (FK)
                    _replace_filing_chunks(session, chunk_rows)
                summaries.append(_summarize_filings(ticker, cik, chunk_rows))
            except Exception:
                logger.exception("filings ingest failed for %s (cik=%d); skipping", ticker, cik)
    return summaries


def print_filings_summary(summaries: list[FilingSummary]) -> None:
    """Print chunk counts per (ticker, item, fiscal_year)."""
    header = f"{'TICKER':<7}{'ITEM':<6}{'FY':>6}{'CHUNKS':>8}"
    print(header)
    print("-" * len(header))
    for s in sorted(summaries, key=lambda s: s.ticker):
        if not s.chunk_counts:
            print(f"{s.ticker:<7}{'-':<6}{'-':>6}{'0':>8}")
            continue
        for item, fy, count in s.chunk_counts:
            print(f"{s.ticker:<7}{item:<6}{fy:>6}{count:>8}")


# --------------------------------------------------------------------------------------------------
# Form 4 lane (insider transactions)
# --------------------------------------------------------------------------------------------------

# Natural key = (accession, insider_name, code, shares, filed); refresh only the rest.
_INSIDER_UPDATE_COLS = ("cik", "role", "price", "value")


@dataclass(frozen=True)
class Form4Summary:
    """Per-company insider buy/sell counts."""

    ticker: str
    cik: int
    buys: int
    sells: int


def _upsert_insiders(session: Session, rows: list[form4.InsiderTxn]) -> None:
    if not rows:
        return
    stmt = _insert(session)(InsiderTransaction).values([r.model_dump() for r in rows])
    stmt = stmt.on_conflict_do_update(
        index_elements=["accession", "insider_name", "code", "shares", "filed"],
        set_={col: getattr(stmt.excluded, col) for col in _INSIDER_UPDATE_COLS},
    )
    session.execute(stmt)


def _summarize_form4(ticker: str, cik: int, rows: list[form4.InsiderTxn]) -> Form4Summary:
    return Form4Summary(
        ticker=ticker,
        cik=cik,
        buys=sum(1 for r in rows if r.code == "P"),
        sells=sum(1 for r in rows if r.code == "S"),
    )


def run_form4(from_cache: bool = False) -> list[Form4Summary]:
    """Ingest the last 12 months of insider P/S transactions for the universe; return summaries."""
    edgar_client.from_cache = from_cache
    tickers = get_settings().universe_tickers
    ticker_map = xbrl.load_ticker_map(tickers)
    as_of = datetime.now(UTC).date()

    summaries: list[Form4Summary] = []
    with session_scope() as session:
        for ticker in tickers:
            resolved = ticker_map.get(ticker)
            if resolved is None:
                continue  # missing ticker already warned by load_ticker_map
            cik, name = resolved
            try:
                records = submissions.recent_filings(submissions.fetch(cik))
                txns = form4.build_insider_txns(cik, records, as_of)
                with session.begin_nested():  # savepoint per company (see run_xbrl)
                    _upsert_company(session, cik, ticker, name)
                    _upsert_insiders(session, txns)
                summaries.append(_summarize_form4(ticker, cik, txns))
            except Exception:
                logger.exception("form4 ingest failed for %s (cik=%d); skipping", ticker, cik)
    return summaries


def print_form4_summary(summaries: list[Form4Summary]) -> None:
    """Print per-company insider buy/sell counts."""
    header = f"{'TICKER':<7}{'BUYS':>6}{'SELLS':>7}"
    print(header)
    print("-" * len(header))
    for s in sorted(summaries, key=lambda s: s.ticker):
        print(f"{s.ticker:<7}{s.buys:>6}{s.sells:>7}")


# --------------------------------------------------------------------------------------------------
# Prices lane (yfinance + stooq fallback)
# --------------------------------------------------------------------------------------------------

# Natural key = (cik, date); refresh the OHLCV + source. "open" is the SQL column name.
_PRICE_UPDATE_COLS = ("open", "high", "low", "close", "volume", "source")


@dataclass(frozen=True)
class PriceSummary:
    """Per-company price row count and provenance."""

    ticker: str
    cik: int
    rows: int
    source: str  # yfinance | stooq | mixed | -


def _upsert_prices(session: Session, rows: list[prices.PriceRow]) -> None:
    if not rows:
        return
    stmt = _insert(session)(Price).values([r.model_dump(by_alias=True) for r in rows])
    stmt = stmt.on_conflict_do_update(
        index_elements=["cik", "date"],
        set_={col: getattr(stmt.excluded, col) for col in _PRICE_UPDATE_COLS},
    )
    session.execute(stmt)


def _summarize_prices(ticker: str, cik: int, rows: list[prices.PriceRow]) -> PriceSummary:
    sources = {r.source for r in rows}
    if not sources:
        source = "-"
    elif len(sources) == 1:
        source = next(iter(sources))
    else:
        source = "mixed"
    return PriceSummary(ticker=ticker, cik=cik, rows=len(rows), source=source)


def run_prices(from_cache: bool = False) -> list[PriceSummary]:
    """Ingest 2y of daily prices for the universe (yfinance, else stooq); return summaries."""
    # The ticker->CIK map still flows through the EDGAR client, so honour --from-cache for it too.
    edgar_client.from_cache = from_cache
    tickers = get_settings().universe_tickers
    ticker_map = xbrl.load_ticker_map(tickers)

    summaries: list[PriceSummary] = []
    with session_scope() as session:
        for ticker in tickers:
            resolved = ticker_map.get(ticker)
            if resolved is None:
                continue  # missing ticker already warned by load_ticker_map
            cik, name = resolved
            try:
                rows = prices.fetch_prices(cik, ticker, from_cache=from_cache)
                with session.begin_nested():  # savepoint per company (see run_xbrl)
                    _upsert_company(session, cik, ticker, name)
                    _upsert_prices(session, rows)
                summaries.append(_summarize_prices(ticker, cik, rows))
            except Exception:
                logger.exception("prices ingest failed for %s (cik=%d); skipping", ticker, cik)
    return summaries


def print_prices_summary(summaries: list[PriceSummary]) -> None:
    """Print per-company price row counts and source."""
    header = f"{'TICKER':<7}{'ROWS':>7}  SOURCE"
    print(header)
    print("-" * len(header))
    for s in sorted(summaries, key=lambda s: s.ticker):
        print(f"{s.ticker:<7}{s.rows:>7}  {s.source}")
