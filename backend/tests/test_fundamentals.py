"""Company identity, annual matrix, and assembled FundamentalsRow set (fundamentals.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from fixtures.rich_seed import EDGECO_CIK, FULLCO_CIK
from tracker.api import schemas
from tracker.db.models import Fundamental
from tracker.services import fiscal, fundamentals, metrics
from tracker.services.fundamentals import FyRow

D = Decimal


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


def test_get_fundamentals_yoy(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    first = _row(result, 2021)
    assert all(cell.value is None and cell.reason is None for cell in first.yoy.values())
    fy2022 = _row(result, 2022)
    assert fy2022.yoy["revenue"].value == pytest.approx(0.25, rel=1e-9)
    assert fy2022.yoy["revenue"].unit == "percent"


def test_get_fundamentals_yoy_mirrors_raw_levels(rich_session: Session) -> None:
    # Schema: "yoy mirrors metrics" — every raw level (non-ratio) has a yoy cell. The five margins
    # are metrics-only; operating_leverage is yoy-only. cost_of_revenue must not be dropped.
    result = fundamentals.get_fundamentals(rich_session, "FULL")
    assert result is not None
    row = _row(result, 2025)
    ratio_only = {"gross_margin", "operating_margin", "net_margin", "fcf_margin", "fcf_conversion"}
    raw_levels = set(row.metrics) - ratio_only
    assert raw_levels <= set(row.yoy)
    assert "cost_of_revenue" in row.yoy
    assert set(row.yoy) - raw_levels == {"operating_leverage"}


def test_get_fundamentals_edgeco_guards(rich_session: Session) -> None:
    result = fundamentals.get_fundamentals(rich_session, "EDGE")
    assert result is not None
    fy2023 = _row(result, 2023)
    assert fy2023.yoy["net_income"].reason == metrics.REASON_YOY_NONPOSITIVE_BASE
    assert fy2023.yoy["operating_leverage"].reason == metrics.REASON_OPLEV_OPINC_SIGN_FLIP
    assert fy2023.metrics["fcf_conversion"].reason == metrics.REASON_FCF_CONV_UNDEFINED
    assert fy2023.metrics["revenue"].superseded_value == pytest.approx(1.05e11, rel=1e-9)

    fy2025 = _row(result, 2025)  # 2024 is a gap -> YoY None with no reason
    assert fy2025.yoy["revenue"].value is None and fy2025.yoy["revenue"].reason is None
    assert fy2025.metrics["shares_diluted"].value is None  # never reported -> P/S None downstream


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
