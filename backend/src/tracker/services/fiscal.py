"""Fiscal-year resolution (PLAN.md §5) — the cross-company "last year" basis (Option A).

Cross-company "last year" is ambiguous when fiscal calendars are misaligned (NVDA ~Jan, MSFT Jun,
AAPL Sep, GOOGL/ETN Dec). The adopted basis is **latest REPORTED fiscal year per company** — the
most recent FY with a filed 10-K in our DB — NOT the latest merely-completed FY. Example: MSFT's
FY2026 has ended but its 10-K is unfiled, so MSFT stays FY2025 while NVDA may already be FY2026.
Each company keeps its own FY, and every comparison labels each value with that FY so the
misalignment is surfaced, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import Fundamental

# Caption every cross-company comparison carries, so the compare basis is explicit to UI + agent.
COMPARE_BASIS_NOTE = "Basis: latest reported fiscal year per company."


def format_fy_label(fiscal_year: int, period_end: date) -> str:
    """Render a fiscal basis, e.g. "FY2025 (ended 2025-09-27)"."""
    return f"FY{fiscal_year} (ended {period_end.isoformat()})"


@dataclass(frozen=True)
class ReportedFiscalYear:
    """A company's latest reported FY and the date it ended."""

    fiscal_year: int
    period_end: date

    @property
    def label(self) -> str:
        return format_fy_label(self.fiscal_year, self.period_end)


def latest_reported_fiscal_year(session: Session, cik: int) -> ReportedFiscalYear | None:
    """The company's most recent FY with filed 10-K fundamentals, or None if it has none yet.

    "Reported" = a fundamentals row with form 10-K exists; its provenance means the 10-K was filed.
    """
    row = session.execute(
        select(Fundamental.fiscal_year, Fundamental.period_end)
        .where(Fundamental.cik == cik, Fundamental.form == "10-K")
        .order_by(Fundamental.fiscal_year.desc(), Fundamental.period_end.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return ReportedFiscalYear(fiscal_year=row[0], period_end=row[1])


def latest_reported_fiscal_year_map(session: Session) -> dict[int, ReportedFiscalYear]:
    """Latest reported FY for every company, resolved independently, in one query.

    Portable across SQLite (unit) and Postgres (integration): reduces in Python instead of a
    Postgres-only DISTINCT ON. Volumes are tiny (~300 fundamentals rows), so this is cheap.
    """
    rows = session.execute(
        select(Fundamental.cik, Fundamental.fiscal_year, Fundamental.period_end).where(
            Fundamental.form == "10-K"
        )
    ).all()
    best: dict[int, ReportedFiscalYear] = {}
    for cik, fiscal_year, period_end in rows:
        current = best.get(cik)
        # Tie-break on (fiscal_year, period_end) to match latest_reported_fiscal_year's ORDER BY, so
        # the two resolvers can never diverge if a restatement ever shifts period_end within a FY.
        if current is None or (fiscal_year, period_end) > (current.fiscal_year, current.period_end):
            best[cik] = ReportedFiscalYear(fiscal_year=fiscal_year, period_end=period_end)
    return best
