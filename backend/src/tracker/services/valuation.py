"""Valuation: the cross-source join — latest close ÷ latest-reported-FY diluted EPS (PLAN.md §4).

Both "as of" bases are explicit: the price date (max stored trading date, never "today") and the EPS
row's fiscal year/accession. Undefined multiples return None-with-reason, never a fake number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import Price
from tracker.services import fundamentals, metrics
from tracker.services.fiscal import ReportedFiscalYear
from tracker.services.fundamentals import FyFacts
from tracker.services.metrics import Metric


@dataclass(frozen=True, slots=True)
class EpsSourceRef:
    """Mirrors schemas.EpsSource — the EPS provenance a valuation answer cites."""

    fiscal_year: int
    period_end: date
    accession: str
    label: str


@dataclass(frozen=True, slots=True)
class ValuationResult:
    """Mirrors schemas.ValuationOut."""

    ticker: str
    cik: int
    trailing_pe: Metric
    trailing_ps: Metric
    close: float
    price_as_of: date
    eps_source: EpsSourceRef
    basis_note: str | None


def get_valuation(session: Session, ticker: str) -> ValuationResult | None:
    """Trailing P/E and P/S for a company, or None if identity/FY/price is missing.

    None (not a degraded payload) when the company is unknown, has no reported FY, or has no stored
    price — ValuationOut.close is required, so a price-less company cannot form a valid payload.
    """
    company = fundamentals.get_company(session, ticker)
    if company is None or company.latest_fiscal_year is None or company.latest_period_end is None:
        return None
    # Reuse the FY get_company already resolved — avoids a second latest-reported-FY query.
    reported = ReportedFiscalYear(company.latest_fiscal_year, company.latest_period_end)
    close_row = session.execute(
        select(Price.close, Price.date)
        .where(Price.cik == company.cik)
        .order_by(Price.date.desc())
        .limit(1)
    ).first()
    if close_row is None:
        return None
    close, price_as_of = close_row[0], close_row[1]

    matrix = fundamentals.get_annual_matrix(session, company.cik)
    facts = next((f for f in matrix if f.fiscal_year == reported.fiscal_year), None)
    if facts is None:
        return None

    eps_fact = facts.concepts.get("eps_diluted")
    rev_fact = facts.concepts.get("revenue")
    shares_fact = facts.concepts.get("shares_diluted")

    trailing_pe = metrics.build_pe(close, eps_fact.value if eps_fact else None)
    trailing_ps = metrics.build_ps(
        close,
        rev_fact.value if rev_fact else None,
        shares_fact.value if shares_fact else None,
    )
    eps_source = EpsSourceRef(
        fiscal_year=reported.fiscal_year,
        period_end=reported.period_end,
        accession=eps_fact.accession if eps_fact else _any_accession(facts),
        label=reported.label,
    )
    return ValuationResult(
        ticker=company.ticker,
        cik=company.cik,
        trailing_pe=trailing_pe,
        trailing_ps=trailing_ps,
        close=float(close),
        price_as_of=price_as_of,
        eps_source=eps_source,
        basis_note=metrics.BASIS_NOTE_PS_WAD,
    )


def _any_accession(facts: FyFacts) -> str:
    """Fallback provenance when eps_diluted is absent: any fact's accession for that FY."""
    for fact in facts.concepts.values():
        return fact.accession
    return ""
