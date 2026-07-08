"""XBRL ingestion runner: resolve the universe, pull company-facts, upsert, print a spot-check.

Postgres in production (ON CONFLICT ... DO UPDATE on the natural key); the same
on_conflict_do_update runs on SQLite so the upsert path is unit-tested without a database service
(fiscal.py sets the dialect-portable precedent). Per the CLAUDE.md error policy a single company
failing is logged and skipped — never a crashed run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tracker.config import get_settings
from tracker.db.models import Company, Fundamental
from tracker.db.session import session_scope
from tracker.ingestion import edgar_client, xbrl
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
