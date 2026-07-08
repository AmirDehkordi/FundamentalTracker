"""Dataset freshness (services/meta.py)."""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.services import meta


def test_freshness_reports_stored_maxima(db_session: Session) -> None:
    result = meta.freshness(db_session)
    assert result.max_price_date == datetime.date(2026, 6, 30)
    assert result.max_filed_date == datetime.date(2025, 11, 1)  # AAPL FY2025 filed
    assert result.company_count == 2
    assert result.source_counts["yfinance"] == 60  # 2 companies x 30 days
    assert result.source_counts["fundamentals"] == 18  # 2 x 3 FYs x 3 concepts


def test_freshness_maps_to_wire_schema(db_session: Session) -> None:
    wire = schemas.FreshnessOut.model_validate(meta.freshness(db_session))
    assert wire.company_count == 2
    assert wire.max_price_date == datetime.date(2026, 6, 30)
