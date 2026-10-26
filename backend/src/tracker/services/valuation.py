"""Valuation: the cross-source join — latest close ÷ latest-reported-FY diluted EPS (PLAN.md §4).

Both "as of" bases are explicit: the price date (max stored trading date, never "today") and the EPS
row's fiscal year/accession. Undefined multiples return None-with-reason, never a fake number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import Company, Price
from tracker.services import fundamentals, metrics
from tracker.services.fiscal import latest_reported_fiscal_year
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


def trailing_multiples(session: Session, cik: int) -> ValuationResult | None:
    """Trailing P/E and P/S for a company by CIK, or None if identity/FY/price is missing.

    None (not a degraded payload) when the company is unknown, has no reported FY, or has no stored
    price — ValuationOut.close is required, so a price-less company cannot form a valid payload. The
    cik-keyed core (like insider/riskdiff/retrieval); get_valuation wraps it by ticker for the REST
    router and the agent tool (PLAN §7).
    """
    company = session.get(Company, cik)
    if company is None:
        return None
    reported = latest_reported_fiscal_year(session, cik)
    if reported is None:
        return None
    close_row = session.execute(
        select(Price.close, Price.date).where(Price.cik == cik).order_by(Price.date.desc()).limit(1)
    ).first()
    if close_row is None:
        return None
    close, price_as_of = close_row[0], close_row[1]

    matrix = fundamentals.get_annual_matrix(session, cik)
    facts = next((f for f in matrix if f.fiscal_year == reported.fiscal_year), None)
    if facts is None:
        return None

    trailing_pe = metrics.build_pe(close, facts.concepts.get("eps_diluted"))
    trailing_ps = metrics.build_ps(
        close, facts.concepts.get("revenue"), facts.concepts.get("shares_diluted")
    )
    eps_prov = facts.provenance.get("eps_diluted")
    eps_source = EpsSourceRef(
        fiscal_year=reported.fiscal_year,
        period_end=reported.period_end,
        accession=eps_prov.accession if eps_prov is not None else _any_accession(facts),
        label=reported.label,
    )
    return ValuationResult(
        ticker=company.ticker,
        cik=cik,
        trailing_pe=trailing_pe,
        trailing_ps=trailing_ps,
        close=float(close),
        price_as_of=price_as_of,
        eps_source=eps_source,
        basis_note=metrics.BASIS_NOTE_PS_WAD,
    )


def get_valuation(session: Session, ticker: str) -> ValuationResult | None:
    """Trailing multiples by ticker (case-insensitive) — the ticker→cik wrapper over the core."""
    company = session.scalars(select(Company).where(Company.ticker == ticker.upper())).one_or_none()
    if company is None:
        return None
    return trailing_multiples(session, company.cik)


def _any_accession(facts: FyFacts) -> str:
    """Fallback provenance when eps_diluted is absent: any concept's accession for that FY."""
    for prov in facts.provenance.values():
        return prov.accession
    return ""
