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


def test_capex_intensity_value_and_guards() -> None:
    assert metrics.capex_intensity(D("20"), D("400")) == pytest.approx(0.05, rel=1e-9)
    assert metrics.capex_intensity(None, D("400")) is None
    assert metrics.capex_intensity(D("20"), None) is None
    assert metrics.capex_intensity(D("20"), D("0")) is None
    assert metrics.capex_intensity(D("20"), D("-1")) is None


def test_capex_intensity_builder() -> None:
    good = metrics.build_capex_intensity(D("20"), D("400"))
    assert good.value == pytest.approx(0.05, rel=1e-9) and good.unit == "percent"
    undefined = metrics.build_capex_intensity(D("20"), D("0"))
    assert undefined.value is None
    assert undefined.reason == metrics.REASON_CAPEX_INTENSITY_UNDEFINED
    missing = metrics.build_capex_intensity(None, D("400"))
    assert missing.value is None and missing.reason is None


def test_reinvestment_ratio_value_and_guards() -> None:
    assert metrics.reinvestment_ratio(D("20"), D("120")) == pytest.approx(1 / 6, rel=1e-9)
    assert metrics.reinvestment_ratio(None, D("120")) is None
    assert metrics.reinvestment_ratio(D("20"), None) is None
    assert metrics.reinvestment_ratio(D("20"), D("0")) is None
    assert metrics.reinvestment_ratio(D("20"), D("-1")) is None


def test_reinvestment_ratio_builder() -> None:
    good = metrics.build_reinvestment_ratio(D("20"), D("120"))
    assert good.value == pytest.approx(1 / 6, rel=1e-9) and good.unit == "ratio"
    undefined = metrics.build_reinvestment_ratio(D("20"), D("0"))
    assert undefined.value is None
    assert undefined.reason == metrics.REASON_REINVESTMENT_UNDEFINED
    missing = metrics.build_reinvestment_ratio(D("20"), None)
    assert missing.value is None and missing.reason is None


def test_build_margin_change_percentage_points() -> None:
    # Margin YoY is a percentage-POINT delta (curr − prev), unit percentage_points — NOT a % change.
    up = metrics.build_margin_change(0.42, 0.40)
    assert up.value == pytest.approx(0.02, rel=1e-9) and up.unit == "percentage_points"
    down = metrics.build_margin_change(0.30, 0.35)
    assert down.value == pytest.approx(-0.05, rel=1e-9)
    # No non-positive-base guard: a pp delta is defined off any base (unlike build_yoy).
    off_neg = metrics.build_margin_change(0.05, -0.10)
    assert off_neg.value == pytest.approx(0.15, rel=1e-9) and off_neg.reason is None
    assert metrics.build_margin_change(None, 0.4).value is None
    assert metrics.build_margin_change(0.4, None).value is None


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
    assert metrics.REASON_CAPEX_INTENSITY_UNDEFINED == "undefined — revenue ≤ 0"
    assert metrics.REASON_REINVESTMENT_UNDEFINED == "undefined — CFO ≤ 0"


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
