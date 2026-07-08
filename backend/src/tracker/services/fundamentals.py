"""Fundamentals: identity, the annual fact matrix, and the assembled FY rows (PLAN.md §6).

Reads already-resolved rows: `Fundamental`'s UNIQUE(cik, concept, fiscal_year, period_end) collapses
restatements at ingest, so a fact is one row carrying its own `superseded_*`; services never redo
latest-filed-wins. Fiscal-year resolution is reused from `fiscal.py` (never reimplemented).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.concepts import CANONICAL_CONCEPTS
from tracker.db.models import Company, Fundamental
from tracker.services import metrics
from tracker.services.fiscal import (
    ReportedFiscalYear,
    format_fy_label,
    latest_reported_fiscal_year,
)
from tracker.services.metrics import Metric, MetricUnit

# Display unit per raw concept (mirrors the stored `unit`, but typed as a MetricUnit Literal so the
# None cells and compare's missing cells still carry the right unit). Shared with services.compare.
CONCEPT_UNITS: dict[str, MetricUnit] = {
    "revenue": "USD",
    "net_income": "USD",
    "gross_profit": "USD",
    "cost_of_revenue": "USD",
    "operating_income": "USD",
    "cfo": "USD",
    "capex": "USD",
    "eps_diluted": "USD/shares",
    "shares_diluted": "shares",
}

# Derived-ratio metric keys compare/compute_metric understand, with their display unit.
DERIVED_UNITS: dict[str, MetricUnit] = {
    "gross_margin": "percent",
    "operating_margin": "percent",
    "net_margin": "percent",
    "fcf_margin": "percent",
    "fcf_conversion": "ratio",
    "operating_leverage": "ratio",
}

# None-with-reason strings for the metric-lookup paths (shared with services.compare).
REASON_NOT_REPORTED = "not reported for latest fiscal year"
REASON_UNKNOWN_METRIC = "unknown metric"


@dataclass(frozen=True, slots=True)
class CompanyRef:
    """Mirrors schemas.CompanyOut."""

    cik: int
    ticker: str
    name: str
    latest_fiscal_year: int | None
    latest_period_end: date | None
    latest_fy_label: str | None


@dataclass(frozen=True, slots=True)
class FactProvenance:
    """Provenance for one fact: which filing reported the value, and any restated prior value."""

    accession: str
    superseded_value: Decimal | None
    superseded_filed: date | None


@dataclass(frozen=True, slots=True)
class FyFacts:
    """Raw matrix record for one fiscal year (PLAN.md §6).

    `concepts` maps concept -> Decimal value (the spec shape). `provenance` is a parallel map
    concept -> FactProvenance (accession + restatement) for the metric cells and citations; callers
    that only want numbers use `concepts`.
    """

    fiscal_year: int
    period_end: date
    label: str
    concepts: dict[str, Decimal]
    provenance: dict[str, FactProvenance]


@dataclass(frozen=True, slots=True)
class FyRow:
    """Mirrors schemas.FundamentalsRow (metrics + prior-FY YoY, both MetricValue-shaped)."""

    fiscal_year: int
    period_end: date
    label: str
    metrics: dict[str, Metric]
    yoy: dict[str, Metric]


@dataclass(frozen=True, slots=True)
class FundamentalsResult:
    """Mirrors schemas.FundamentalsOut. `rows` chronological ascending."""

    ticker: str
    cik: int
    name: str
    rows: list[FyRow]


def get_company(session: Session, ticker: str) -> CompanyRef | None:
    """Identity + latest reported FY. None for an unknown ticker (case-insensitive)."""
    company = session.scalars(select(Company).where(Company.ticker == ticker.upper())).one_or_none()
    if company is None:
        return None
    fy = latest_reported_fiscal_year(session, company.cik)
    return CompanyRef(
        cik=company.cik,
        ticker=company.ticker,
        name=company.name,
        latest_fiscal_year=fy.fiscal_year if fy else None,
        latest_period_end=fy.period_end if fy else None,
        latest_fy_label=fy.label if fy else None,
    )


def get_latest_completed_fy(session: Session, cik: int) -> ReportedFiscalYear | None:
    """Latest *reported* FY (delegates to fiscal.latest_reported_fiscal_year).

    The P4 task names this "completed", but the frozen basis is latest reported — a completed-but-
    unreported year (e.g. MSFT FY2026 before its 10-K files) stays out. Delegating keeps the one
    resolver so a divergent "completed" answer can never appear.
    """
    return latest_reported_fiscal_year(session, cik)


def get_annual_matrix(session: Session, cik: int) -> list[FyFacts]:
    """Per-FY canonical facts, ascending by fiscal_year. Excludes derivation inputs (sga/rnd)."""
    rows = session.scalars(
        select(Fundamental).where(
            Fundamental.cik == cik,
            Fundamental.form == "10-K",  # symmetry with fiscal.latest_reported_fiscal_year
            Fundamental.concept.in_(CANONICAL_CONCEPTS),
        )
    ).all()
    by_fy: dict[int, list[Fundamental]] = defaultdict(list)
    for row in rows:
        by_fy[row.fiscal_year].append(row)

    matrix: list[FyFacts] = []
    for fiscal_year in sorted(by_fy):
        fy_rows = by_fy[fiscal_year]
        # A fiscal-calendar change can leave two period_ends under one FY label; take the latest.
        period_end = max(row.period_end for row in fy_rows)
        surviving = [row for row in fy_rows if row.period_end == period_end]
        concepts = {row.concept: row.value for row in surviving}
        provenance = {
            row.concept: FactProvenance(
                accession=row.accession,
                superseded_value=row.superseded_value,
                superseded_filed=row.superseded_filed,
            )
            for row in surviving
        }
        matrix.append(
            FyFacts(
                fiscal_year=fiscal_year,
                period_end=period_end,
                label=format_fy_label(fiscal_year, period_end),
                concepts=concepts,
                provenance=provenance,
            )
        )
    return matrix


def get_fundamentals(session: Session, ticker: str) -> FundamentalsResult | None:
    """Assemble the FundamentalsRow set (concepts + ratios + YoY). None for unknown ticker."""
    company = get_company(session, ticker)
    if company is None:
        return None
    matrix = get_annual_matrix(session, company.cik)
    index = {facts.fiscal_year: facts for facts in matrix}
    rows = [_build_row(facts, index.get(facts.fiscal_year - 1)) for facts in matrix]
    return FundamentalsResult(ticker=company.ticker, cik=company.cik, name=company.name, rows=rows)


def compute_metric(
    session: Session, cik: int, metric_key: str, reported: ReportedFiscalYear
) -> Metric:
    """One derived-metric cell for a reported FY — the single source compare delegates to."""
    matrix = get_annual_matrix(session, cik)
    index = {facts.fiscal_year: facts for facts in matrix}
    facts = index.get(reported.fiscal_year)
    unit = DERIVED_UNITS.get(metric_key, "ratio")
    if facts is None:
        return Metric(value=None, unit=unit, reason=REASON_NOT_REPORTED)

    rev = _concept_value(facts, "revenue")
    if metric_key == "gross_margin":
        return metrics.plain(metrics.gross_margin(_concept_value(facts, "gross_profit"), rev), unit)
    if metric_key == "operating_margin":
        oi = _concept_value(facts, "operating_income")
        return metrics.plain(metrics.operating_margin(oi, rev), unit)
    if metric_key == "net_margin":
        return metrics.plain(metrics.net_margin(_concept_value(facts, "net_income"), rev), unit)
    if metric_key == "fcf_margin":
        cfo = _concept_value(facts, "cfo")
        capex = _concept_value(facts, "capex")
        return metrics.plain(metrics.fcf_margin(cfo, capex, rev), unit)
    if metric_key == "fcf_conversion":
        cfo = _concept_value(facts, "cfo")
        capex = _concept_value(facts, "capex")
        return metrics.build_fcf_conversion(cfo, capex, _concept_value(facts, "net_income"))
    if metric_key == "operating_leverage":
        prior = index.get(reported.fiscal_year - 1)
        prior_oi = _concept_value(prior, "operating_income") if prior else None
        prior_rev = _concept_value(prior, "revenue") if prior else None
        return metrics.build_operating_leverage(
            _concept_value(facts, "operating_income"), prior_oi, rev, prior_rev
        )
    return Metric(value=None, unit=unit, reason=REASON_UNKNOWN_METRIC)


def _concept_value(facts: FyFacts, concept: str) -> Decimal | None:
    return facts.concepts.get(concept)


def _raw_cell(facts: FyFacts, concept: str) -> Metric:
    unit = CONCEPT_UNITS[concept]
    value = facts.concepts.get(concept)
    if value is None:
        return Metric(value=None, unit=unit)
    prov = facts.provenance.get(concept)
    return Metric(
        value=float(value),
        unit=unit,
        accession=prov.accession if prov is not None else None,
        superseded_value=(
            float(prov.superseded_value)
            if prov is not None and prov.superseded_value is not None
            else None
        ),
        superseded_filed=prov.superseded_filed if prov is not None else None,
    )


def _build_row(facts: FyFacts, prior: FyFacts | None) -> FyRow:
    rev = _concept_value(facts, "revenue")
    gp = _concept_value(facts, "gross_profit")
    oi = _concept_value(facts, "operating_income")
    ni = _concept_value(facts, "net_income")
    cfo = _concept_value(facts, "cfo")
    capex = _concept_value(facts, "capex")

    # Insertion order = display order (KPI row + table, PLAN.md §9). fcf (a derived USD level) sits
    # after capex; the five ratios follow the raw concepts.
    metric_cells: dict[str, Metric] = {
        "revenue": _raw_cell(facts, "revenue"),
        "cost_of_revenue": _raw_cell(facts, "cost_of_revenue"),
        "gross_profit": _raw_cell(facts, "gross_profit"),
        "operating_income": _raw_cell(facts, "operating_income"),
        "net_income": _raw_cell(facts, "net_income"),
        "eps_diluted": _raw_cell(facts, "eps_diluted"),
        "cfo": _raw_cell(facts, "cfo"),
        "capex": _raw_cell(facts, "capex"),
        "fcf": metrics.plain(metrics.fcf(cfo, capex), "USD"),
        "shares_diluted": _raw_cell(facts, "shares_diluted"),
        "gross_margin": metrics.plain(metrics.gross_margin(gp, rev), "percent"),
        "operating_margin": metrics.plain(metrics.operating_margin(oi, rev), "percent"),
        "net_margin": metrics.plain(metrics.net_margin(ni, rev), "percent"),
        "fcf_margin": metrics.plain(metrics.fcf_margin(cfo, capex, rev), "percent"),
        "fcf_conversion": metrics.build_fcf_conversion(cfo, capex, ni),
    }

    def prior_value(concept: str) -> Decimal | None:
        return _concept_value(prior, concept) if prior else None

    yoy_cells: dict[str, Metric] = {
        "revenue": metrics.build_yoy(rev, prior_value("revenue")),
        "cost_of_revenue": metrics.build_yoy(
            _concept_value(facts, "cost_of_revenue"), prior_value("cost_of_revenue")
        ),
        "gross_profit": metrics.build_yoy(gp, prior_value("gross_profit")),
        "operating_income": metrics.build_yoy(oi, prior_value("operating_income")),
        "net_income": metrics.build_yoy(ni, prior_value("net_income")),
        "eps_diluted": metrics.build_yoy(
            _concept_value(facts, "eps_diluted"), prior_value("eps_diluted")
        ),
        "cfo": metrics.build_yoy(cfo, prior_value("cfo")),
        "capex": metrics.build_yoy(capex, prior_value("capex")),
        "fcf": metrics.build_yoy(
            metrics.fcf_amount(cfo, capex),
            metrics.fcf_amount(prior_value("cfo"), prior_value("capex")),
        ),
        "shares_diluted": metrics.build_yoy(
            _concept_value(facts, "shares_diluted"), prior_value("shares_diluted")
        ),
        "operating_leverage": metrics.build_operating_leverage(
            oi, prior_value("operating_income"), rev, prior_value("revenue")
        ),
    }

    return FyRow(
        fiscal_year=facts.fiscal_year,
        period_end=facts.period_end,
        label=facts.label,
        metrics=metric_cells,
        yoy=yoy_cells,
    )
