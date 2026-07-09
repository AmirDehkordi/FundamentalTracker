"""Price window + 10-K markers (services/prices.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import Company, Filing, Price
from tracker.services import prices

D = Decimal


def test_get_prices_rows_and_markers(db_session: Session) -> None:
    result = prices.get_prices(db_session, "aapl")  # case-insensitive
    assert result is not None
    assert result.ticker == "AAPL" and result.cik == 320193 and result.range == "2y"
    assert len(result.rows) == 30  # mini_seed seeds 30 daily rows
    assert result.rows[0].date < result.rows[-1].date  # ascending
    assert result.rows[-1].close == 179.0 and result.rows[-1].date == datetime.date(2026, 6, 30)
    assert len(result.filings) == 3  # AAPL FY2023-2025 10-Ks
    assert all(marker.form == "10-K" for marker in result.filings)
    # Volume rides on every row per the frozen PriceRow contract (the chart plots it).
    assert all(isinstance(r.volume, int) and r.volume > 0 for r in result.rows)


def test_get_prices_range_window(db_session: Session) -> None:
    # An old row sits inside the 2y window but outside 1m (relative to max date 2026-06-30).
    db_session.add(
        Price(
            cik=320193,
            date=datetime.date(2025, 5, 1),
            open_=D("1"),
            high=D("1"),
            low=D("1"),
            close=D("1"),
            volume=1,
            source="stooq",
        )
    )
    db_session.commit()
    one_month = prices.get_prices(db_session, "AAPL", "1m")
    two_year = prices.get_prices(db_session, "AAPL", "2y")
    assert one_month is not None and two_year is not None
    assert all(r.date >= datetime.date(2026, 5, 30) for r in one_month.rows)  # old row excluded
    assert any(r.date == datetime.date(2025, 5, 1) for r in two_year.rows)  # old row included


def test_get_prices_invalid_range_defaults_to_2y(db_session: Session) -> None:
    result = prices.get_prices(db_session, "AAPL", "bogus")
    assert result is not None and result.range == "2y"


def test_get_prices_unknown_ticker(db_session: Session) -> None:
    assert prices.get_prices(db_session, "NOPE") is None


def test_get_prices_no_prices_returns_empty_rows(db_session: Session) -> None:
    # A known company with filings but no price rows -> empty chart that still carries 10-K markers.
    db_session.add(Company(cik=888, ticker="NOPX", name="No Prices Co."))
    db_session.add(
        Filing(
            accession="0000000888-2025-10K",
            cik=888,
            form="10-K",
            fiscal_year=2025,
            period_end=datetime.date(2025, 12, 31),
            filed=datetime.date(2026, 2, 1),
            primary_doc_url="https://sec.gov/x",
        )
    )
    db_session.commit()
    result = prices.get_prices(db_session, "NOPX")
    assert result is not None
    assert result.rows == []
    assert len(result.filings) == 1


def test_get_prices_maps_to_wire_schema(db_session: Session) -> None:
    result = prices.get_prices(db_session, "AAPL")
    assert result is not None
    wire = schemas.PricesOut.model_validate(result)
    assert wire.ticker == "AAPL"
    assert isinstance(wire.rows[0], schemas.PriceRow)
    assert isinstance(wire.filings[0], schemas.FilingMarker)
