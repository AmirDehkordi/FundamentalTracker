"""Company identity, annual matrix, and assembled FundamentalsRow set (fundamentals.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from fixtures.rich_seed import EDGECO_CIK, FULLCO_CIK
from tracker.api import schemas
from tracker.db.models import Company, Fundamental
from tracker.services import fiscal, fundamentals, metrics
from tracker.services.fundamentals import FyRow

D = Decimal

SPLITCO_CIK = 1000003

# Four FYs spanning a 10:1 split between FY2022 and FY2023 (shares 2.5e9 -> 25e9), NVDA-shaped:
# the stored FY2022 comparatives keep the pre-split basis. eps stays = net_income / shares.
_SPLITCO_SERIES: dict[int, dict[str, Decimal]] = {
    2021: {
        "revenue": D("90000000000"),
        "net_income": D("8000000000"),
        "eps_diluted": D("3.2"),
        "shares_diluted": D("2500000000"),
    },
    2022: {
        "revenue": D("100000000000"),
        "net_income": D("10000000000"),
        "eps_diluted": D("4"),
        "shares_diluted": D("2500000000"),
    },
    2023: {
        "revenue": D("110000000000"),
        "net_income": D("12500000000"),
        "eps_diluted": D("0.5"),
        "shares_diluted": D("25000000000"),
    },
    2024: {
        "revenue": D("120000000000"),
        "net_income": D("15000000000"),
        "eps_diluted": D("0.6"),
        "shares_diluted": D("25000000000"),
    },
}


def _seed_splitco(session: Session) -> None:
    session.add(Company(cik=SPLITCO_CIK, ticker="SPLT", name="Split Co."))
    for fy, facts in _SPLITCO_SERIES.items():
        for concept, value in facts.items():
            session.add(
                Fundamental(
                    cik=SPLITCO_CIK,
                    concept=concept,
                    source_tag=f"us-gaap:{concept}",
                    fiscal_year=fy,
                    period_start=datetime.date(fy, 1, 1),
                    period_end=datetime.date(fy, 12, 31),
                    value=value,
                    unit=fundamentals.CONCEPT_UNITS[concept],
                    accession=f"{SPLITCO_CIK:010d}-{fy}-10K",
                    filed=datetime.date(fy + 1, 3, 1),
                    form="10-K",
                )
            )
    session.commit()


def _row(result: fundamentals.FundamentalsResult, fiscal_year: int) -> FyRow:
    return next(r for r in result.rows if r.fiscal_year == fiscal_year)


def test_get_company(rich_session: Session) -> None:
    company = fundamentals.get_company(rich_session, "full")  # case-insensitive
    assert company is not None
    assert company.cik == FULLCO_CIK
    assert company.ticker == "FULL"
    assert company.name == "Full Co."
    assert company.latest_fiscal_year == 2025
    assert company.latest_period_end == datetime.date(2025, 12, 31)
    assert company.latest_fy_label == "FY2025 (ended 2025-12-31)"


def test_get_company_unknown(rich_session: Session) -> None:
    assert fundamentals.get_company(rich_session, "NOPE") is None


def test_list_companies(db_session: Session) -> None:
    companies = fundamentals.list_companies(db_session)
    assert [c.ticker for c in companies] == ["AAPL", "NVDA"]  # ascending by ticker
    assert companies[0].latest_fiscal_year == 2025
    assert companies[0].latest_fy_label == "FY2025 (ended 2025-09-27)"
    assert companies[0].market_cap is None  # mini_seed has no shares_diluted


def test_list_companies_market_cap(rich_session: Session) -> None:
    companies = {c.ticker: c for c in fundamentals.list_companies(rich_session)}
    # close 179 (latest of 30 days from 150) x shares_diluted 16e9 at FY2025 (FULLCO's latest FY).
    assert companies["FULL"].market_cap == D("179") * D("16000000000")
    assert companies["EDGE"].market_cap is None  # EDGECO has no shares_diluted


def test_get_latest_completed_fy_delegates(rich_session: Session) -> None:
    result = fundamentals.get_latest_completed_fy(rich_session, FULLCO_CIK)
    assert result == fiscal.latest_reported_fiscal_year(rich_session, FULLCO_CIK)
    assert result is not None and result.fiscal_year == 2025


def test_annual_matrix_ascending_with_all_concepts(rich_session: Session) -> None:
    matrix = fundamentals.get_annual_matrix(rich_session, FULLCO_CIK)
    assert [f.fiscal_year for f in matrix] == [2021, 2022, 2023, 2024, 2025]
    latest = matrix[-1]
    assert latest.label == "FY2025 (ended 2025-12-31)"
    assert latest.concepts["revenue"] == D("400000000000")
    assert latest.concepts["shares_diluted"] == D("16000000000")
    assert set(latest.concepts) == {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps_diluted",
        "cfo",
        "capex",
        "shares_diluted",
    }


def test_annual_matrix_has_fiscal_year_gap(rich_session: Session) -> None:
    matrix = fundamentals.get_annual_matrix(rich_session, EDGECO_CIK)
    assert [f.fiscal_year for f in matrix] == [2022, 2023, 2025]  # 2024 skipped


def test_annual_matrix_captures_superseded(rich_session: Session) -> None:
    matrix = fundamentals.get_annual_matrix(rich_session, EDGECO_CIK)
    fy2023 = next(f for f in matrix if f.fiscal_year == 2023)
    assert fy2023.concepts["revenue"] == D("110000000000")  # surviving (latest-filed) value
    prov = fy2023.provenance["revenue"]
    assert prov.superseded_value == D("105000000000")
    assert prov.superseded_filed == datetime.date(2023, 3, 1)


def test_annual_matrix_picks_latest_period_end(rich_session: Session) -> None:
    # A fiscal-calendar change leaves two period_ends under one FY label; the later one wins.
    rich_session.add(
        Fundamental(
            cik=FULLCO_CIK,
            concept="revenue",
            source_tag="us-gaap:Revenues",
            fiscal_year=2025,
            period_start=datetime.date(2025, 1, 1),
            period_end=datetime.date(2025, 6, 30),  # earlier than the 12-31 row
            value=D("1"),
            unit="USD",
            accession="stub",
            filed=datetime.date(2025, 8, 1),
            form="10-K",
        )
    )
    rich_session.commit()
    matrix = fundamentals.get_annual_matrix(rich_session, FULLCO_CIK)
    fy2025 = next(f for f in matrix if f.fiscal_year == 2025)
    assert fy2025.period_end == datetime.date(2025, 12, 31)
    assert fy2025.concepts["revenue"] == D("400000000000")  # the 6-30 stub is excluded


def test_get_fundamentals_metrics_units_and_values(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    row = _row(result, 2025)
    assert row.metrics["revenue"].value == pytest.approx(4e11, rel=1e-9)
    assert row.metrics["revenue"].unit == "USD"
    assert row.metrics["revenue"].accession == "0001000001-2025-10K"
    assert row.metrics["gross_margin"].value == pytest.approx(0.375, rel=1e-9)
    assert row.metrics["gross_margin"].unit == "percent"
    assert row.metrics["fcf"].value == pytest.approx(1e11, rel=1e-9)
    assert row.metrics["fcf"].unit == "USD"
    assert row.metrics["fcf_conversion"].value == pytest.approx(100 / 112, rel=1e-9)
    assert row.metrics["fcf_conversion"].unit == "ratio"
    # capex = revenue * 0.05, cfo = revenue * 0.30 (rich_seed._fullco_facts).
    assert row.metrics["capex_intensity"].value == pytest.approx(0.05, rel=1e-9)
    assert row.metrics["capex_intensity"].unit == "percent"
    assert row.metrics["reinvestment_ratio"].value == pytest.approx(1 / 6, rel=1e-9)
    assert row.metrics["reinvestment_ratio"].unit == "ratio"


def test_get_fundamentals_yoy(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    first = _row(result, 2021)
    assert all(cell.value is None and cell.reason is None for cell in first.yoy.values())
    fy2022 = _row(result, 2022)
    assert fy2022.yoy["revenue"].value == pytest.approx(0.25, rel=1e-9)
    assert fy2022.yoy["revenue"].unit == "percent"


def test_get_fundamentals_yoy_mirrors_raw_levels(rich_session: Session) -> None:
    # Every raw level (non-ratio) has a % YoY cell. cost_of_revenue must not be dropped. The seven
    # ratios (margins + fcf_conversion + capex_intensity + reinvestment_ratio) all carry a
    # percentage-point YoY instead.
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    row = _row(result, 2025)
    margins = {
        "gross_margin",
        "operating_margin",
        "net_margin",
        "fcf_margin",
        "fcf_conversion",
        "capex_intensity",
        "reinvestment_ratio",
    }
    raw_levels = set(row.metrics) - margins
    assert raw_levels <= set(row.yoy)
    assert "cost_of_revenue" in row.yoy
    assert set(row.yoy) - raw_levels == margins
    # Margin YoY is a percentage-point delta.
    assert row.yoy["gross_margin"].unit == "percentage_points"
    assert row.yoy["capex_intensity"].unit == "percentage_points"


def test_get_fundamentals_edgeco_guards(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "EDGE")
    assert result is not None
    fy2023 = _row(result, 2023)
    assert fy2023.yoy["net_income"].reason == metrics.REASON_YOY_NONPOSITIVE_BASE
    assert fy2023.metrics["fcf_conversion"].reason == metrics.REASON_FCF_CONV_UNDEFINED
    assert fy2023.metrics["revenue"].superseded_value == pytest.approx(1.05e11, rel=1e-9)
    # capex 3e9 / revenue 110e9, capex 3e9 / cfo 8e9 — both well-defined despite the other guards.
    assert fy2023.metrics["capex_intensity"].value == pytest.approx(3 / 110, rel=1e-9)
    assert fy2023.metrics["reinvestment_ratio"].value == pytest.approx(0.375, rel=1e-9)

    fy2025 = _row(result, 2025)  # 2024 is a gap -> YoY None with no reason
    assert fy2025.yoy["revenue"].value is None and fy2025.yoy["revenue"].reason is None
    assert fy2025.metrics["shares_diluted"].value is None  # never reported -> P/S None downstream


def test_split_boundary_suppresses_per_share_yoy(rich_session: Session) -> None:
    _seed_splitco(rich_session)
    result = fundamentals.get_fundamentals(rich_session, "SPLT")
    assert result is not None

    # (i) At the 10:1 boundary both per-share YoY cells are n.m. with the split reason — the raw
    # ratio (0.5/4 − 1 ≈ −87.5%) must never surface.
    boundary = _row(result, 2023)
    for key in ("eps_diluted", "shares_diluted"):
        cell = boundary.yoy[key]
        assert cell.value is None
        assert cell.reason == metrics.REASON_YOY_SHARE_BASIS_CHANGE

    # (iii) Non-per-share YoY on the boundary row is untouched (splits don't change dollars).
    assert boundary.yoy["revenue"].value == pytest.approx(0.10, rel=1e-9)
    assert boundary.yoy["net_income"].value == pytest.approx(0.25, rel=1e-9)

    # (ii) Same-basis years on both sides keep their normal per-share YoY.
    before = _row(result, 2022)
    assert before.yoy["eps_diluted"].value == pytest.approx(0.25, rel=1e-9)
    assert before.yoy["shares_diluted"].value == pytest.approx(0.0, abs=1e-12)
    after = _row(result, 2024)
    assert after.yoy["eps_diluted"].value == pytest.approx(0.2, rel=1e-9)
    assert after.yoy["shares_diluted"].value == pytest.approx(0.0, abs=1e-12)


def test_get_fundamentals_unknown_ticker(rich_session: Session) -> None:
    assert fundamentals.get_fundamentals(rich_session, "NOPE") is None


def test_get_fundamentals_maps_to_wire_schema(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    wire = schemas.FundamentalsOut.model_validate(result)
    assert wire.ticker == "FULL"
    assert [r.fiscal_year for r in wire.rows] == [2021, 2022, 2023, 2024, 2025]
    assert isinstance(wire.rows[-1].metrics["gross_margin"], schemas.MetricValue)


def test_compute_metric_absent_fy(rich_session: Session) -> None:
    absent = fiscal.ReportedFiscalYear(1999, datetime.date(1999, 12, 31))
    cell = fundamentals.compute_metric(rich_session, FULLCO_CIK, "gross_margin", absent)
    assert cell.value is None
    assert cell.reason == "not reported for latest fiscal year"
    assert cell.unit == "percent"


def test_compute_metric_unknown_key(rich_session: Session) -> None:
    reported = fiscal.latest_reported_fiscal_year(rich_session, FULLCO_CIK)
    assert reported is not None
    cell = fundamentals.compute_metric(rich_session, FULLCO_CIK, "not_a_metric", reported)
    assert cell.value is None and cell.reason == "unknown metric"


def test_compute_metric_revenue_yoy(rich_session: Session) -> None:
    reported = fiscal.latest_reported_fiscal_year(rich_session, FULLCO_CIK)
    assert reported is not None
    cell = fundamentals.compute_metric(rich_session, FULLCO_CIK, "revenue_yoy", reported)
    assert cell.value == pytest.approx(400 / 350 - 1, rel=1e-9)  # FY2024->FY2025
    assert cell.unit == "percent"


def test_compute_metric_revenue_yoy_gap(rich_session: Session) -> None:
    reported = fiscal.latest_reported_fiscal_year(rich_session, EDGECO_CIK)
    assert reported is not None  # EDGECO's latest reported FY is 2025
    cell = fundamentals.compute_metric(rich_session, EDGECO_CIK, "revenue_yoy", reported)
    assert cell.value is None and cell.reason is None  # FY2024 gap -> prior revenue missing
