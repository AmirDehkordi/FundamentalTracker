"""Compare: one metric across the universe on the latest-reported-FY-per-company basis (PLAN.md §5).

Each cell footnotes its OWN fiscal year, so the calendar misalignment (NVDA ~Jan vs AAPL Sep, both
"FY2025") is surfaced, not hidden. Raw concepts resolve here (carrying restatement provenance);
derived ratios delegate to fundamentals.compute_metric so a formula lives in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.concepts import is_canonical_concept
from tracker.db.models import Company, Fundamental
from tracker.services import fundamentals
from tracker.services.fiscal import (
    COMPARE_BASIS_NOTE,
    ReportedFiscalYear,
    latest_reported_fiscal_year_map,
)
from tracker.services.fundamentals import (
    CONCEPT_UNITS,
    DERIVED_UNITS,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_METRIC,
)
from tracker.services.metrics import Metric


@dataclass(frozen=True, slots=True)
class CompareRow:
    """Mirrors schemas.CompareCell."""

    ticker: str
    cik: int
    value: Metric
    fiscal_year: int
    period_end: date
    label: str


@dataclass(frozen=True, slots=True)
class CompareResult:
    """Mirrors schemas.CompareOut."""

    metric: str
    basis_note: str
    rows: list[CompareRow]


def compare(session: Session, metric: str) -> CompareResult:
    """One metric across every company with a reported 10-K, each labelled with its own FY."""
    fy_map = latest_reported_fiscal_year_map(session)
    companies = {c.cik: c for c in session.scalars(select(Company)).all()}
    rows: list[CompareRow] = []
    # Skip any cik with no companies row (unreachable under the FK); keeps compare non-raising.
    known = [cik for cik in fy_map if cik in companies]
    for cik in sorted(known, key=lambda c: companies[c].ticker):
        reported = fy_map[cik]
        rows.append(
            CompareRow(
                ticker=companies[cik].ticker,
                cik=cik,
                value=_value_for(session, cik, metric, reported),
                fiscal_year=reported.fiscal_year,
                period_end=reported.period_end,
                label=reported.label,
            )
        )
    return CompareResult(metric=metric, basis_note=COMPARE_BASIS_NOTE, rows=rows)


def _value_for(session: Session, cik: int, metric: str, reported: ReportedFiscalYear) -> Metric:
    if is_canonical_concept(metric):
        row = session.scalars(
            select(Fundamental).where(
                Fundamental.cik == cik,
                Fundamental.concept == metric,
                Fundamental.fiscal_year == reported.fiscal_year,
                Fundamental.period_end == reported.period_end,
            )
        ).one_or_none()
        if row is None:
            return Metric(value=None, unit=CONCEPT_UNITS[metric], reason=REASON_NOT_REPORTED)
        return Metric(
            value=float(row.value),
            unit=CONCEPT_UNITS[metric],
            accession=row.accession,
            superseded_value=(
                float(row.superseded_value) if row.superseded_value is not None else None
            ),
            superseded_filed=row.superseded_filed,
        )
    if metric in DERIVED_UNITS:
        return fundamentals.compute_metric(session, cik, metric, reported)
    return Metric(value=None, unit="ratio", reason=REASON_UNKNOWN_METRIC)
