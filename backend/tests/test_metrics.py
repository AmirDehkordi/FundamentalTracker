"""Pure metric functions + builders (services/metrics.py) — every guard branch, no DB."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from tracker.api import schemas
from tracker.services import metrics

D = Decimal


def test_margins_values() -> None:
    assert metrics.gross_margin(D("150"), D("400")) == pytest.approx(0.375, rel=1e-9)
    assert metrics.operating_margin(D("100"), D("400")) == pytest.approx(0.25, rel=1e-9)
    assert metrics.net_margin(D("-10"), D("100")) == pytest.approx(-0.1, rel=1e-9)


def test_margins_none_guards() -> None:
    assert metrics.gross_margin(None, D("400")) is None
    assert metrics.gross_margin(D("150"), None) is None
    assert metrics.gross_margin(D("150"), D("0")) is None
    assert metrics.operating_margin(None, D("1")) is None
    assert metrics.operating_margin(D("1"), D("0")) is None
    assert metrics.net_margin(D("1"), None) is None
    assert metrics.net_margin(D("1"), D("0")) is None


def test_fcf_and_margin() -> None:
    assert metrics.fcf(D("120"), D("20")) == pytest.approx(100.0, rel=1e-9)
    assert metrics.fcf(None, D("20")) is None
    assert metrics.fcf(D("120"), None) is None
    assert metrics.fcf_margin(D("120"), D("20"), D("400")) == pytest.approx(0.25, rel=1e-9)
    assert metrics.fcf_margin(None, D("20"), D("400")) is None
    assert metrics.fcf_margin(D("120"), D("20"), None) is None
    assert metrics.fcf_margin(D("120"), D("20"), D("0")) is None
    assert metrics.fcf_amount(None, None) is None


def test_fcf_conversion_and_builder() -> None:
    assert metrics.fcf_conversion(D("120"), D("20"), D("112")) == pytest.approx(100 / 112, rel=1e-9)
    assert metrics.fcf_conversion(D("120"), D("20"), D("0")) is None
    assert metrics.fcf_conversion(D("120"), D("20"), D("-5")) is None
    assert metrics.fcf_conversion(None, D("20"), D("100")) is None

    good = metrics.build_fcf_conversion(D("120"), D("20"), D("112"))
    assert good.value == pytest.approx(100 / 112, rel=1e-9) and good.unit == "ratio"
    undefined = metrics.build_fcf_conversion(D("120"), D("20"), D("0"))
    assert undefined.value is None and undefined.reason == metrics.REASON_FCF_CONV_UNDEFINED
    missing = metrics.build_fcf_conversion(None, D("20"), D("100"))
    assert missing.value is None and missing.reason is None


def test_yoy_and_builder() -> None:
    assert metrics.yoy(D("110"), D("100")) == pytest.approx(0.1, rel=1e-9)
    assert metrics.yoy(None, D("100")) is None
    assert metrics.yoy(D("110"), None) is None
    assert metrics.yoy(D("110"), D("0")) is None
    assert metrics.yoy(D("110"), D("-5")) is None
    assert metrics.eps_growth(D("7"), D("6")) == pytest.approx(1 / 6, rel=1e-9)

    up = metrics.build_yoy(D("125"), D("100"))
    assert up.value == pytest.approx(0.25, rel=1e-9) and up.unit == "percent"
    gap = metrics.build_yoy(None, D("100"))
    assert gap.value is None and gap.reason is None
    flip = metrics.build_yoy(D("5"), D("-10"))
    assert flip.value is None and flip.reason == metrics.REASON_YOY_NONPOSITIVE_BASE


def test_operating_leverage_value() -> None:
    assert metrics.operating_leverage(D("130"), D("113.75"), D("400"), D("350")) == pytest.approx(
        0.325, rel=1e-9
    )
    assert metrics.operating_leverage(None, D("1"), D("2"), D("1")) is None


def test_operating_leverage_builder_reasons() -> None:
    declined = metrics.build_operating_leverage(D("50"), D("40"), D("100"), D("110"))
    assert declined.value is None and declined.reason == metrics.REASON_OPLEV_REVENUE_DECLINED
    flat = metrics.build_operating_leverage(D("50"), D("40"), D("1000"), D("995"))
    assert flat.value is None and flat.reason == metrics.REASON_OPLEV_REVENUE_FLAT
    flip = metrics.build_operating_leverage(D("3"), D("-5"), D("110"), D("100"))
    assert flip.value is None and flip.reason == metrics.REASON_OPLEV_OPINC_SIGN_FLIP
    missing = metrics.build_operating_leverage(None, D("1"), D("2"), D("1"))
    assert missing.value is None and missing.reason is None
    good = metrics.build_operating_leverage(D("130"), D("113.75"), D("400"), D("350"))
    assert good.value == pytest.approx(0.325, rel=1e-9) and good.unit == "ratio"
    # Both revenues zero: the flat guard catches ΔRev == 0, so the division never runs.
    assert metrics.operating_leverage(D("1"), D("2"), D("0"), D("0")) is None
    zero_rev = metrics.build_operating_leverage(D("1"), D("2"), D("0"), D("0"))
    assert zero_rev.value is None and zero_rev.reason == metrics.REASON_OPLEV_REVENUE_FLAT


def test_build_pe() -> None:
    good = metrics.build_pe(D("179"), D("7"))
    assert good.value == pytest.approx(179 / 7, rel=1e-9) and good.unit == "ratio"
    assert metrics.build_pe(D("179"), D("0")).reason == metrics.REASON_PE_NEGATIVE_EPS
    neg = metrics.build_pe(D("179"), D("-1"))
    assert neg.value is None and neg.reason == metrics.REASON_PE_NEGATIVE_EPS
    assert metrics.build_pe(None, D("7")).value is None
    assert metrics.build_pe(None, D("7")).reason is None
    assert metrics.build_pe(D("179"), None).value is None


def test_build_ps() -> None:
    good = metrics.build_ps(D("179"), D("400000000000"), D("16000000000"))
    assert good.value == pytest.approx(7.16, rel=1e-9) and good.unit == "ratio"
    assert metrics.build_ps(D("179"), D("400000000000"), None).value is None
    assert metrics.build_ps(D("179"), None, D("16000000000")).value is None
    assert metrics.build_ps(None, D("1"), D("1")).value is None
    assert metrics.build_ps(D("179"), D("0"), D("16000000000")).value is None
    assert metrics.build_ps(D("179"), D("400000000000"), D("0")).value is None


def test_reason_constants_exact_glyphs() -> None:
    # Byte-for-byte with PLAN.md §6 and test_schemas.py (em dash U+2014, ≤ U+2264).
    assert metrics.REASON_PE_NEGATIVE_EPS == "n.m. — negative EPS"
    assert metrics.REASON_FCF_CONV_UNDEFINED == "undefined — net income ≤ 0"
    assert metrics.REASON_YOY_NONPOSITIVE_BASE == "sign change / non-positive base"
    assert metrics.REASON_OPLEV_REVENUE_DECLINED == "n.m. — revenue declined"
    assert metrics.REASON_OPLEV_REVENUE_FLAT == "n.m. — revenue change < 1%"
    assert metrics.REASON_OPLEV_OPINC_SIGN_FLIP == "n.m. — operating income changed sign"


def test_metric_maps_to_wire_schema() -> None:
    cell = metrics.Metric(
        value=None,
        unit="ratio",
        reason="r",
        accession="acc",
        superseded_value=1.5,
        superseded_filed=datetime.date(2020, 1, 1),
    )
    wire = schemas.MetricValue.model_validate(cell)
    assert wire.value is None
    assert wire.unit == "ratio"
    assert wire.reason == "r"
    assert wire.accession == "acc"
    assert wire.superseded_value == 1.5
    assert wire.superseded_filed == datetime.date(2020, 1, 1)

    plain = schemas.MetricValue.model_validate(metrics.plain(25.5, "ratio"))
    assert plain.value == 25.5
    assert plain.reason is None
