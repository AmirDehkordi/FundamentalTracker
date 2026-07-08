"""Latest-reported-FY resolution (services/fiscal.py) — the Option A cross-company basis."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from tracker.db.models import Fundamental
from tracker.services import fiscal


def test_format_fy_label() -> None:
    assert fiscal.format_fy_label(2025, datetime.date(2025, 9, 27)) == "FY2025 (ended 2025-09-27)"


def test_latest_reported_fy_picks_latest_year(db_session: Session) -> None:
    aapl = fiscal.latest_reported_fiscal_year(db_session, 320193)
    assert aapl is not None
    assert aapl.fiscal_year == 2025
    assert aapl.period_end == datetime.date(2025, 9, 27)
    assert aapl.label == "FY2025 (ended 2025-09-27)"


def test_each_company_keeps_its_own_period_end(db_session: Session) -> None:
    # Same latest FY number, but misaligned calendars -> different period-ends (the trap, surfaced).
    aapl = fiscal.latest_reported_fiscal_year(db_session, 320193)
    nvda = fiscal.latest_reported_fiscal_year(db_session, 1045810)
    assert aapl is not None and nvda is not None
    assert aapl.period_end == datetime.date(2025, 9, 27)
    assert nvda.period_end == datetime.date(2025, 1, 25)


def test_companies_resolve_independently(db_session: Session) -> None:
    # Give NVDA a newer reported year; AAPL must be unaffected.
    db_session.add(
        Fundamental(
            cik=1045810,
            concept="revenue",
            source_tag="us-gaap:Revenues",
            fiscal_year=2026,
            period_start=datetime.date(2025, 1, 26),
            period_end=datetime.date(2026, 1, 25),
            value=Decimal("200000000000"),
            unit="USD",
            accession="nvda-2026",
            filed=datetime.date(2026, 2, 25),
            form="10-K",
        )
    )
    db_session.commit()

    result = fiscal.latest_reported_fiscal_year_map(db_session)
    assert result[1045810].fiscal_year == 2026  # NVDA advanced
    assert result[320193].fiscal_year == 2025  # AAPL unchanged


def test_none_when_company_has_no_reported_data(db_session: Session) -> None:
    assert fiscal.latest_reported_fiscal_year(db_session, 999999) is None
