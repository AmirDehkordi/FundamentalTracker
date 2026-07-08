"""Trailing P/E and P/S cross-source join (services/valuation.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from fixtures.rich_seed import FULLCO_CIK
from tracker.api import schemas
from tracker.db.models import Company, Fundamental, Price
from tracker.services import metrics, valuation

D = Decimal


def _fundamental(cik: int, concept: str, value: Decimal, unit: str) -> Fundamental:
    return Fundamental(
        cik=cik,
        concept=concept,
        source_tag=f"us-gaap:{concept}",
        fiscal_year=2025,
        period_start=datetime.date(2025, 1, 1),
        period_end=datetime.date(2025, 12, 31),
        value=value,
        unit=unit,
        accession=f"{cik:010d}-2025-10K",
        filed=datetime.date(2026, 3, 1),
        form="10-K",
    )


def test_valuation_happy_path(rich_session: Session) -> None:
    result = valuation.get_valuation(rich_session, "FULL")
    assert result is not None
    assert result.trailing_pe.value == pytest.approx(179 / 7, rel=1e-9)
    assert result.trailing_pe.unit == "ratio"
    assert result.trailing_ps.value == pytest.approx(7.16, rel=1e-9)
    assert result.close == pytest.approx(179.0, rel=1e-9)
    assert result.price_as_of == datetime.date(2026, 6, 30)
    assert result.eps_source.fiscal_year == 2025
    assert result.eps_source.period_end == datetime.date(2025, 12, 31)
    assert result.eps_source.accession == "0001000001-2025-10K"
    assert result.eps_source.label == "FY2025 (ended 2025-12-31)"
    assert result.basis_note == metrics.BASIS_NOTE_PS_WAD


def test_trailing_multiples_by_cik(rich_session: Session) -> None:
    by_cik = valuation.trailing_multiples(rich_session, FULLCO_CIK)
    by_ticker = valuation.get_valuation(rich_session, "FULL")
    assert by_cik is not None and by_ticker is not None
    assert by_cik == by_ticker  # the ticker wrapper delegates to the cik core
    assert by_cik.trailing_pe.value == pytest.approx(179 / 7, rel=1e-9)


def test_trailing_multiples_unknown_cik(rich_session: Session) -> None:
    assert valuation.trailing_multiples(rich_session, 99999999) is None


def test_valuation_negative_eps_and_missing_shares(rich_session: Session) -> None:
    result = valuation.get_valuation(rich_session, "EDGE")
    assert result is not None
    assert result.trailing_pe.value is None
    assert result.trailing_pe.reason == metrics.REASON_PE_NEGATIVE_EPS
    assert result.trailing_ps.value is None  # EDGECO never reports shares_diluted
    assert result.eps_source.fiscal_year == 2025  # latest reported FY, correctly resolved
    assert result.eps_source.period_end == datetime.date(2025, 12, 31)


def test_valuation_reported_fy_without_canonical_facts(rich_session: Session) -> None:
    # Latest 10-K FY carries only a derivation-input concept (sga), absent from the canonical
    # matrix, so there is no facts row for the reported FY -> None (covers the facts-None branch).
    rich_session.add(Company(cik=1000006, ticker="SGAO", name="Sga Only"))
    rich_session.add(_fundamental(1000006, "sga", D("100"), "USD"))
    rich_session.add(
        Price(
            cik=1000006,
            date=datetime.date(2026, 6, 1),
            open_=D("10"),
            high=D("11"),
            low=D("9"),
            close=D("10"),
            volume=1000,
            source="yfinance",
        )
    )
    rich_session.commit()
    assert valuation.get_valuation(rich_session, "SGAO") is None


def test_valuation_unknown_ticker(rich_session: Session) -> None:
    assert valuation.get_valuation(rich_session, "NOPE") is None


def test_valuation_no_prices_returns_none(rich_session: Session) -> None:
    rich_session.add(Company(cik=1000004, ticker="NOPX", name="No Prices"))
    rich_session.add(_fundamental(1000004, "eps_diluted", D("5"), "USD/shares"))
    rich_session.commit()
    assert valuation.get_valuation(rich_session, "NOPX") is None


def test_valuation_no_reported_fy_returns_none(rich_session: Session) -> None:
    # A company with prices but no filed 10-K facts has no reported FY -> no valuation basis.
    rich_session.add(Company(cik=1000005, ticker="NOFY", name="No Filed FY"))
    rich_session.add(
        Price(
            cik=1000005,
            date=datetime.date(2026, 6, 1),
            open_=D("10"),
            high=D("11"),
            low=D("9"),
            close=D("10"),
            volume=1000,
            source="yfinance",
        )
    )
    rich_session.commit()
    assert valuation.get_valuation(rich_session, "NOFY") is None


def test_valuation_missing_eps_uses_fallback_accession(rich_session: Session) -> None:
    rich_session.add(Company(cik=1000003, ticker="NOEP", name="No Eps"))
    rich_session.add(_fundamental(1000003, "revenue", D("100000000000"), "USD"))
    rich_session.add(_fundamental(1000003, "shares_diluted", D("10000000000"), "shares"))
    rich_session.add(
        Price(
            cik=1000003,
            date=datetime.date(2026, 6, 1),
            open_=D("50"),
            high=D("51"),
            low=D("49"),
            close=D("50"),
            volume=1000,
            source="yfinance",
        )
    )
    rich_session.commit()
    result = valuation.get_valuation(rich_session, "NOEP")
    assert result is not None
    assert result.trailing_pe.value is None and result.trailing_pe.reason is None
    assert result.trailing_ps.value == pytest.approx(50 / 10, rel=1e-9)  # 50 / (100e9/10e9)
    assert result.eps_source.accession == "0001000003-2025-10K"  # fallback to a present concept


def test_valuation_maps_to_wire_schema(rich_session: Session) -> None:
    result = valuation.get_valuation(rich_session, "FULL")
    assert result is not None
    wire = schemas.ValuationOut.model_validate(result)
    assert wire.trailing_pe.value == pytest.approx(179 / 7, rel=1e-9)
    assert wire.eps_source.accession == "0001000001-2025-10K"
