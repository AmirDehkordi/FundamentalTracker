"""Schema round-trips on SQLite (db/models.py + mini_seed)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tracker.db.models import Company, FilingChunk, Fundamental, Price


def test_companies_seeded_and_ordered(db_session: Session) -> None:
    companies = db_session.scalars(select(Company).order_by(Company.ticker)).all()
    assert [c.ticker for c in companies] == ["AAPL", "NVDA"]


def test_fundamentals_carry_provenance(db_session: Session) -> None:
    rows = db_session.scalars(
        select(Fundamental).where(Fundamental.cik == 320193, Fundamental.concept == "revenue")
    ).all()
    assert len(rows) == 3
    latest = max(rows, key=lambda r: r.fiscal_year)
    assert latest.accession and latest.form == "10-K"
    assert isinstance(latest.value, Decimal)
    # Restatement columns are nullable and empty in a clean seed.
    assert latest.superseded_value is None
    assert latest.superseded_filed is None


def test_prices_and_chunks_counts(db_session: Session) -> None:
    price_count = db_session.scalar(select(func.count()).select_from(Price))
    assert price_count == 60  # 2 companies x 30 days
    chunks = db_session.scalars(select(FilingChunk)).all()
    assert len(chunks) == 4


def test_unique_constraint_rejects_duplicate_fact(db_session: Session) -> None:
    # Same natural key as a seeded AAPL FY2025 revenue row.
    db_session.add(
        Fundamental(
            cik=320193,
            concept="revenue",
            source_tag="dupe",
            fiscal_year=2025,
            period_end=datetime.date(2025, 9, 27),
            value=Decimal("1"),
            unit="USD",
            accession="dupe",
            filed=datetime.date(2025, 10, 1),
            form="10-K",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
