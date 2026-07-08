"""Frozen contract behavior (api/schemas.py)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import Company


def test_metric_value_none_with_reason() -> None:
    mv = schemas.MetricValue(value=None, unit="ratio", reason="n.m. — negative EPS")
    assert mv.value is None
    assert mv.reason is not None and mv.reason.startswith("n.m.")


def test_decimal_value_coerces_to_float_on_the_wire() -> None:
    mv = schemas.MetricValue(value=Decimal("130500000000.00"), unit="USD")
    assert isinstance(mv.value, float)
    assert mv.value == 130500000000.0


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        schemas.CompanyOut(cik=1, ticker="X", name="Y", bogus=1)  # type: ignore[call-arg]


def test_ask_request_requires_nonempty_question() -> None:
    with pytest.raises(ValidationError):
        schemas.AskRequest(question="")
    ok = schemas.AskRequest(question="What is NVDA revenue?")
    assert ok.history == []


def test_final_answer_defaults() -> None:
    fa = schemas.FinalAnswer(answer_md="hello")
    assert fa.declined is False
    assert fa.citations == []
    assert fa.trace == []
    assert fa.decline_reason is None


def test_company_out_from_orm_attributes(db_session: Session) -> None:
    company = db_session.scalars(select(Company)).first()
    assert company is not None
    out = schemas.CompanyOut.model_validate(company)
    assert out.ticker == company.ticker
    assert out.latest_fiscal_year is None  # not populated until ingestion
