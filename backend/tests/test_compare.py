"""Cross-company compare on the latest-reported-FY-per-company basis (services/compare.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import Company, Fundamental
from tracker.services import compare
from tracker.services.fiscal import COMPARE_BASIS_NOTE

D = Decimal


def _cell(result: compare.CompareResult, ticker: str) -> compare.CompareRow:
    return next(r for r in result.rows if r.ticker == ticker)


def test_compare_revenue_sorted_by_ticker(db_session: Session) -> None:
    result = compare.compare(db_session, "revenue")
    assert result.metric == "revenue"
    assert result.basis_note == COMPARE_BASIS_NOTE
    assert [r.ticker for r in result.rows] == ["AAPL", "NVDA"]
    assert _cell(result, "AAPL").value.value == pytest.approx(3e11, rel=1e-9)  # FY2025 scale x3


def test_compare_labels_expose_misaligned_year_ends(db_session: Session) -> None:
    result = compare.compare(db_session, "revenue")
    assert _cell(result, "AAPL").label == "FY2025 (ended 2025-09-27)"
    assert _cell(result, "NVDA").label == "FY2025 (ended 2025-01-25)"


def test_compare_raw_missing_metric(db_session: Session) -> None:
    result = compare.compare(db_session, "capex")  # not seeded in mini_seed
    for row in result.rows:
        assert row.value.value is None
        assert row.value.reason == compare.REASON_NOT_REPORTED
        assert row.value.unit == "USD"


def test_compare_unknown_metric(db_session: Session) -> None:
    result = compare.compare(db_session, "bogus_metric")
    for row in result.rows:
        assert row.value.value is None
        assert row.value.reason == compare.REASON_UNKNOWN_METRIC
        assert row.value.unit == "ratio"


def test_compare_excludes_company_without_reported_fy(db_session: Session) -> None:
    db_session.add(Company(cik=555, ticker="ZZZZ", name="No Filings Co."))
    db_session.commit()
    result = compare.compare(db_session, "revenue")
    assert [r.ticker for r in result.rows] == ["AAPL", "NVDA"]  # ZZZZ has no 10-K facts


def test_compare_derived_gross_margin(rich_session: Session) -> None:
    result = compare.compare(rich_session, "gross_margin")
    assert _cell(result, "FULL").value.value == pytest.approx(0.375, rel=1e-9)
    assert _cell(result, "EDGE").value.value == pytest.approx(0.25, rel=1e-9)
    assert _cell(result, "FULL").value.unit == "percent"


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("operating_margin", 0.325),
        ("net_margin", 0.28),
        ("fcf_margin", 0.25),
        ("fcf_conversion", 100 / 112),
        ("capex_intensity", 0.05),
        ("reinvestment_ratio", 1 / 6),
    ],
)
def test_compare_derived_metrics(rich_session: Session, metric: str, expected: float) -> None:
    result = compare.compare(rich_session, metric)
    assert _cell(result, "FULL").value.value == pytest.approx(expected, rel=1e-9)


def test_compare_revenue_yoy(rich_session: Session) -> None:
    result = compare.compare(rich_session, "revenue_yoy")
    # FY2024->FY2025 revenue growth = 400/350 - 1; same basis as the per-FY fundamentals yoy cell.
    assert _cell(result, "FULL").value.value == pytest.approx(400 / 350 - 1, rel=1e-9)
    assert _cell(result, "FULL").value.unit == "percent"
    # EDGECO skips FY2024, so FY2025 has no prior-year revenue — None, no reason (missing input).
    edge = _cell(result, "EDGE")
    assert edge.value.value is None and edge.value.reason is None


def test_compare_carries_restatement_provenance(rich_session: Session) -> None:
    rich_session.add(Company(cik=1000009, ticker="SUPS", name="Restated Co."))
    rich_session.add(
        Fundamental(
            cik=1000009,
            concept="revenue",
            source_tag="us-gaap:Revenues",
            fiscal_year=2025,
            period_start=datetime.date(2025, 1, 1),
            period_end=datetime.date(2025, 12, 31),
            value=D("100000000000"),
            unit="USD",
            accession="0001000009-2025-10K",
            filed=datetime.date(2026, 3, 1),
            form="10-K",
            superseded_value=D("95000000000"),
            superseded_filed=datetime.date(2025, 3, 1),
        )
    )
    rich_session.commit()
    result = compare.compare(rich_session, "revenue")
    sups = _cell(result, "SUPS")
    assert sups.value.accession == "0001000009-2025-10K"
    assert sups.value.superseded_value == pytest.approx(9.5e10, rel=1e-9)


def test_compare_maps_to_wire_schema(db_session: Session) -> None:
    result = compare.compare(db_session, "revenue")
    wire = schemas.CompareOut.model_validate(result)
    assert wire.metric == "revenue"
    assert wire.basis_note == COMPARE_BASIS_NOTE
    assert isinstance(wire.rows[0].value, schemas.MetricValue)
