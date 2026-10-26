"""Meta: dataset freshness for the footer (PLAN.md §9/§10).

Reports stored maxima and row counts, never "today" — the UI labels how fresh the seed is instead of
implying live data. Mirrors schemas.FreshnessOut.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker.db.models import Company, Filing, Fundamental, Price


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """Mirrors schemas.FreshnessOut."""

    max_price_date: date | None
    max_filed_date: date | None
    source_counts: dict[str, int]
    company_count: int


def freshness(session: Session) -> FreshnessResult:
    """Latest stored price/filing dates, per-source + fundamentals row counts, and company count."""
    max_price_date: date | None = session.scalar(select(func.max(Price.date)))
    max_filed_date: date | None = session.scalar(select(func.max(Filing.filed)))
    company_count: int = session.scalar(select(func.count()).select_from(Company)) or 0

    source_counts: dict[str, int] = {}
    for source, count in session.execute(
        select(Price.source, func.count()).group_by(Price.source)
    ).all():
        source_counts[source] = count
    source_counts["fundamentals"] = (
        session.scalar(select(func.count()).select_from(Fundamental)) or 0
    )

    return FreshnessResult(
        max_price_date=max_price_date,
        max_filed_date=max_filed_date,
        source_counts=source_counts,
        company_count=company_count,
    )
