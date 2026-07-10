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
from tracker.services import metrics, prices
from tracker.services.fiscal import (
    ReportedFiscalYear,
    format_fy_label,
    latest_reported_fiscal_year,
    latest_reported_fiscal_year_map,
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
    "capex_intensity": "percent",
    "reinvestment_ratio": "ratio",
    "revenue_yoy": "percent",
}

# None-with-reason strings for the metric-lookup paths (shared with services.compare).
REASON_NOT_REPORTED = "not reported for latest fiscal year"
REASON_UNKNOWN_METRIC = "unknown metric"


@dataclass(frozen=True, slots=True)
class CompanyRef:
    """Mirrors schemas.CompanyOut.

    `market_cap` = latest close x latest-reported-FY diluted shares (same approximation
    metrics.build_ps uses for P/S — weighted-avg diluted shares, not period-end shares outstanding).
    Only list_companies populates it (batched); get_company leaves it None so the per-ticker
    resolver used by every panel route + agent tool call stays a single cheap query.
    """

    cik: int
    ticker: str
    name: str
    latest_fiscal_year: int | None
    latest_period_end: date | None
    latest_fy_label: str | None
    market_cap: Decimal | None = None


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


def _latest_shares_diluted_map(
    session: Session, latest: dict[int, ReportedFiscalYear]
) -> dict[int, Decimal]:
    """cik -> shares_diluted value at exactly that company's latest reported FY, in one query."""
    if not latest:
        return {}
    rows = session.execute(
        select(Fundamental.cik, Fundamental.fiscal_year, Fundamental.value).where(
            Fundamental.concept == "shares_diluted", Fundamental.form == "10-K"
        )
    ).all()
    result: dict[int, Decimal] = {}
    for cik, fiscal_year, value in rows:
        target = latest.get(cik)
        if target is not None and target.fiscal_year == fiscal_year:
            result[cik] = value
    return result


def list_companies(session: Session) -> list[CompanyRef]:
    """The tracked universe, ascending by ticker, each with its latest reported FY (PLAN §5).

    market_cap is None-with-no-reason (a CompanyOut field, not a MetricValue) whenever the latest
    reported FY has no stored price or no shares_diluted — same missing-input cases build_ps hits.
    """
    companies = session.scalars(select(Company).order_by(Company.ticker)).all()
    latest = latest_reported_fiscal_year_map(session)
    shares = _latest_shares_diluted_map(session, latest)
    closes = prices.latest_close_map(session)
    result: list[CompanyRef] = []
    for c in companies:
        fy = latest.get(c.cik)
        close = closes.get(c.cik)
        share_count = shares.get(c.cik)
        market_cap = (
            close[0] * share_count if close is not None and share_count is not None else None
        )
        result.append(
            CompanyRef(
                cik=c.cik,
                ticker=c.ticker,
                name=c.name,
                latest_fiscal_year=fy.fiscal_year if fy else None,
                latest_period_end=fy.period_end if fy else None,
                latest_fy_label=fy.label if fy else None,
                market_cap=market_cap,
            )
        )
    return result


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
    if metric_key == "capex_intensity":
        return metrics.build_capex_intensity(_concept_value(facts, "capex"), rev)
    if metric_key == "reinvestment_ratio":
        cfo = _concept_value(facts, "cfo")
        return metrics.build_reinvestment_ratio(_concept_value(facts, "capex"), cfo)
    if metric_key == "revenue_yoy":
        # Same basis as the per-FY yoy["revenue"] cell, so compare and the matrix never disagree.
        prior = index.get(reported.fiscal_year - 1)
        prior_rev = _concept_value(prior, "revenue") if prior else None
        return metrics.build_yoy(rev, prior_rev)
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
    # after capex; the seven ratios follow the raw concepts.
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
        "capex_intensity": metrics.build_capex_intensity(capex, rev),
        "reinvestment_ratio": metrics.build_reinvestment_ratio(capex, cfo),
    }

    def prior_value(concept: str) -> Decimal | None:
        return _concept_value(prior, concept) if prior else None

    prev_rev = prior_value("revenue")
    prev_oi = prior_value("operating_income")
    prev_gp = prior_value("gross_profit")
    prev_ni = prior_value("net_income")
    prev_cfo = prior_value("cfo")
    prev_capex = prior_value("capex")

    # NVDA trap: a prior FY outside the latest filing's restated-comparative window keeps its
    # pre-split share basis, so eps/share-count YoY across the boundary is a fiction (≈−96% for a
    # 10:1 split). Suppress at read time rather than back-adjust stored values (DESIGN.md §6).
    basis_break = metrics.share_basis_break(
        _concept_value(facts, "shares_diluted"), prior_value("shares_diluted")
    )

    yoy_cells: dict[str, Metric] = {
        # Absolute levels + fcf: relative % change (build_yoy).
        "revenue": metrics.build_yoy(rev, prev_rev),
        "cost_of_revenue": metrics.build_yoy(
            _concept_value(facts, "cost_of_revenue"), prior_value("cost_of_revenue")
        ),
        "gross_profit": metrics.build_yoy(gp, prev_gp),
        "operating_income": metrics.build_yoy(oi, prev_oi),
        "net_income": metrics.build_yoy(ni, prev_ni),
        "eps_diluted": metrics.build_share_basis_yoy(
            _concept_value(facts, "eps_diluted"), prior_value("eps_diluted"), basis_break
        ),
        "cfo": metrics.build_yoy(cfo, prev_cfo),
        "capex": metrics.build_yoy(capex, prev_capex),
        "fcf": metrics.build_yoy(
            metrics.fcf_amount(cfo, capex),
            metrics.fcf_amount(prev_cfo, prev_capex),
        ),
        "shares_diluted": metrics.build_share_basis_yoy(
            _concept_value(facts, "shares_diluted"), prior_value("shares_diluted"), basis_break
        ),
        # Margins + fcf_conversion: percentage-POINT delta (curr margin − prior margin).
        "gross_margin": metrics.build_margin_change(
            metrics.gross_margin(gp, rev), metrics.gross_margin(prev_gp, prev_rev)
        ),
        "operating_margin": metrics.build_margin_change(
            metrics.operating_margin(oi, rev), metrics.operating_margin(prev_oi, prev_rev)
        ),
        "net_margin": metrics.build_margin_change(
            metrics.net_margin(ni, rev), metrics.net_margin(prev_ni, prev_rev)
        ),
        "fcf_margin": metrics.build_margin_change(
            metrics.fcf_margin(cfo, capex, rev), metrics.fcf_margin(prev_cfo, prev_capex, prev_rev)
        ),
        "fcf_conversion": metrics.build_margin_change(
            metrics.fcf_conversion(cfo, capex, ni),
            metrics.fcf_conversion(prev_cfo, prev_capex, prev_ni),
        ),
        "capex_intensity": metrics.build_margin_change(
            metrics.capex_intensity(capex, rev), metrics.capex_intensity(prev_capex, prev_rev)
        ),
        "reinvestment_ratio": metrics.build_margin_change(
            metrics.reinvestment_ratio(capex, cfo), metrics.reinvestment_ratio(prev_capex, prev_cfo)
        ),
    }

    return FyRow(
        fiscal_year=facts.fiscal_year,
        period_end=facts.period_end,
        label=facts.label,
        metrics=metric_cells,
        yoy=yoy_cells,
    )
