"""Pure metric functions + the shared MetricValue-shaped cell (PLAN.md §6).

Two layers live here. The *scalar* functions (`gross_margin`, `yoy`, `capex_intensity`,
…) are pure math: they take `Decimal | None` off the ORM, do all arithmetic in `Decimal` (exact
guards for sign/zero tests), return `float | None`, and NEVER raise on bad data.
The *builder* functions (`build_pe`, `build_yoy`, …) wrap a scalar into a `Metric` and attach the
right None-with-reason string. Reason selection sits beside the guards, so a caller never misreads a
`None` (a bare `float | None` can't say whether an input was missing or a guard tripped).

`Metric` mirrors `schemas.MetricValue` field-for-field; services never import the wire schema. P5
maps a `Metric` to `MetricValue` via `MetricValue.model_validate(metric)` (APIModel is
`from_attributes=True`). Values are `float` here (the wire type); magnitudes stay inside float's
exact integer range (2^53 ≈ 9e15) as the schema docstring notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

# Mirrors schemas.MetricUnit; a local Literal so services never import the frozen wire module.
MetricUnit = Literal["USD", "USD/shares", "shares", "percent", "ratio", "percentage_points"]


@dataclass(frozen=True, slots=True)
class Metric:
    """One metric cell, mirroring schemas.MetricValue. `reason` is set iff `value is None`."""

    value: float | None
    unit: MetricUnit
    reason: str | None = None
    accession: str | None = None
    superseded_value: float | None = None
    superseded_filed: date | None = None


# Reason wording. FROZEN glyphs (em dash U+2014, ≤ U+2264) match PLAN.md §6 and test_schemas.py.
REASON_PE_NEGATIVE_EPS = "n.m. — negative EPS"
REASON_FCF_CONV_UNDEFINED = "undefined — net income ≤ 0"
REASON_YOY_NONPOSITIVE_BASE = "sign change / non-positive base"
REASON_CAPEX_INTENSITY_UNDEFINED = "undefined — revenue ≤ 0"
REASON_REINVESTMENT_UNDEFINED = "undefined — CFO ≤ 0"
REASON_YOY_SHARE_BASIS_CHANGE = "n.m. — share basis change (stock split)"

# Split detector threshold. Real splits are ≥ 2:1 while organic dilution/buybacks move diluted
# weighted-average shares a few percent a year, so 1.5 sits safely between the two regimes.
SHARE_BASIS_BREAK_RATIO = Decimal("1.5")

# P/S share-basis caveat (decision log #11): diluted WAD shares understate buybacks.
BASIS_NOTE_PS_WAD = "P/S uses diluted weighted-average shares; understates buybacks."


def plain(value: float | None, unit: MetricUnit) -> Metric:
    """Wrap an already-computed value with no reason (margins, raw levels)."""
    return Metric(value=value, unit=unit)


# ---------------------------------------------------------------------------
# scalar metrics — Decimal in, float out, never raise
# ---------------------------------------------------------------------------


def gross_margin(gross_profit: Decimal | None, revenue: Decimal | None) -> float | None:
    """gross_profit / revenue. None if either missing or revenue == 0."""
    if gross_profit is None or revenue is None or revenue == 0:
        return None
    return float(gross_profit / revenue)


def operating_margin(operating_income: Decimal | None, revenue: Decimal | None) -> float | None:
    """operating_income / revenue. None if either missing or revenue == 0."""
    if operating_income is None or revenue is None or revenue == 0:
        return None
    return float(operating_income / revenue)


def net_margin(net_income: Decimal | None, revenue: Decimal | None) -> float | None:
    """net_income / revenue (may be negative). None if either missing or revenue == 0."""
    if net_income is None or revenue is None or revenue == 0:
        return None
    return float(net_income / revenue)


def fcf_amount(cfo: Decimal | None, capex: Decimal | None) -> Decimal | None:
    """CFO − capex, kept at full Decimal precision for margin/conversion reuse."""
    if cfo is None or capex is None:
        return None
    return cfo - capex


def fcf(cfo: Decimal | None, capex: Decimal | None) -> float | None:
    """Free cash flow = CFO − capex. None if either input missing."""
    amount = fcf_amount(cfo, capex)
    return None if amount is None else float(amount)


def fcf_margin(cfo: Decimal | None, capex: Decimal | None, revenue: Decimal | None) -> float | None:
    """FCF / revenue. None if any input missing or revenue == 0."""
    amount = fcf_amount(cfo, capex)
    if amount is None or revenue is None or revenue == 0:
        return None
    return float(amount / revenue)


def fcf_conversion(
    cfo: Decimal | None, capex: Decimal | None, net_income: Decimal | None
) -> float | None:
    """FCF / net_income (earnings quality). None if FCF missing or net_income ≤ 0 (undefined)."""
    amount = fcf_amount(cfo, capex)
    if amount is None or net_income is None or net_income <= 0:
        return None
    return float(amount / net_income)


def share_basis_break(curr_shares: Decimal | None, prev_shares: Decimal | None) -> bool:
    """True when adjacent-FY diluted shares jump ≥ 1.5x either way (split-style basis change).

    A prior FY outside the latest filing's restated-comparative window keeps its pre-split share
    basis, so a per-share YoY across that boundary compares two currencies. Missing or non-positive
    inputs → False (nothing to judge; the ordinary YoY guards handle those).
    """
    if curr_shares is None or prev_shares is None or curr_shares <= 0 or prev_shares <= 0:
        return False
    hi, lo = (
        (curr_shares, prev_shares) if curr_shares >= prev_shares else (prev_shares, curr_shares)
    )
    return hi / lo >= SHARE_BASIS_BREAK_RATIO


def yoy(curr: Decimal | None, prev: Decimal | None) -> float | None:
    """curr / prev − 1. None if either missing; None if prev ≤ 0.

    Uniform None-on-non-positive-base for every concept (§6): percent growth off a ≤0 base is not
    meaningful (−100 to +50 is not "+150%"), so a signed delta is deliberately NOT substituted.
    """
    if curr is None or prev is None or prev <= 0:
        return None
    return float(curr / prev - 1)


def eps_growth(eps_curr: Decimal | None, eps_prev: Decimal | None) -> float | None:
    """Diluted-EPS YoY — yoy() applied to EPS."""
    return yoy(eps_curr, eps_prev)


def capex_intensity(capex: Decimal | None, revenue: Decimal | None) -> float | None:
    """Capex / revenue — how much of each revenue dollar is reinvested in fixed assets/infra
    (does the AI build-out outrun the cash the business generates). None if either input missing
    or revenue <= 0."""
    if capex is None or revenue is None or revenue <= 0:
        return None
    return float(capex / revenue)


def reinvestment_ratio(capex: Decimal | None, cfo: Decimal | None) -> float | None:
    """Capex / CFO — the share of operating cash flow consumed by capex (does the AI build-out
    outrun the cash the business generates). None if either input missing or cfo <= 0."""
    if capex is None or cfo is None or cfo <= 0:
        return None
    return float(capex / cfo)


# ---------------------------------------------------------------------------
# builders — scalar + the correct None-with-reason, as a Metric cell
# ---------------------------------------------------------------------------


def build_yoy(curr: Decimal | None, prev: Decimal | None) -> Metric:
    """YoY cell (percent). Missing input → reason None; prev ≤ 0 → non-positive-base reason."""
    value = yoy(curr, prev)
    if value is not None:
        return Metric(value=value, unit="percent")
    if curr is None or prev is None:
        return Metric(value=None, unit="percent")
    return Metric(value=None, unit="percent", reason=REASON_YOY_NONPOSITIVE_BASE)


def build_share_basis_yoy(curr: Decimal | None, prev: Decimal | None, basis_break: bool) -> Metric:
    """build_yoy for per-share/share-count concepts: a detected share-basis break (stock split)
    makes the ratio meaningless whatever the inputs, so it wins over every other outcome."""
    if basis_break:
        return Metric(value=None, unit="percent", reason=REASON_YOY_SHARE_BASIS_CHANGE)
    return build_yoy(curr, prev)


def build_capex_intensity(capex: Decimal | None, revenue: Decimal | None) -> Metric:
    """Capex-intensity cell (percent) = capex / revenue. Missing input → None; revenue ≤ 0 →
    undefined reason."""
    value = capex_intensity(capex, revenue)
    if value is not None:
        return Metric(value=value, unit="percent")
    if capex is None or revenue is None:
        return Metric(value=None, unit="percent")
    return Metric(value=None, unit="percent", reason=REASON_CAPEX_INTENSITY_UNDEFINED)


def build_reinvestment_ratio(capex: Decimal | None, cfo: Decimal | None) -> Metric:
    """Reinvestment-ratio cell (ratio) = capex / CFO. Missing input → None; CFO ≤ 0 → undefined
    reason."""
    value = reinvestment_ratio(capex, cfo)
    if value is not None:
        return Metric(value=value, unit="ratio")
    if capex is None or cfo is None:
        return Metric(value=None, unit="ratio")
    return Metric(value=None, unit="ratio", reason=REASON_REINVESTMENT_UNDEFINED)


def build_margin_change(curr: float | None, prev: float | None) -> Metric:
    """Margin/ratio YoY as a PERCENTAGE-POINT delta (curr − prev), unit 'percentage_points'.

    Distinct from build_yoy's relative % change: a margin going 40%→42% is +2.0 pp, not +5%.
    Inputs are the already-computed margin floats (gross/operating/net/FCF margin, FCF conversion).
    None if either margin is missing; no non-positive-base guard (a pp delta needs no such base).
    """
    if curr is None or prev is None:
        return Metric(value=None, unit="percentage_points")
    return Metric(value=curr - prev, unit="percentage_points")


def build_fcf_conversion(
    cfo: Decimal | None, capex: Decimal | None, net_income: Decimal | None
) -> Metric:
    """FCF-conversion cell (ratio). Missing input → None; net_income ≤ 0 → undefined reason."""
    value = fcf_conversion(cfo, capex, net_income)
    if value is not None:
        return Metric(value=value, unit="ratio")
    if fcf_amount(cfo, capex) is None or net_income is None:
        return Metric(value=None, unit="ratio")
    return Metric(value=None, unit="ratio", reason=REASON_FCF_CONV_UNDEFINED)


def build_pe(close: Decimal | None, eps: Decimal | None) -> Metric:
    """Trailing P/E cell (unit ratio) = close / EPS. eps ≤ 0 → 'n.m. — negative EPS'."""
    if close is None or eps is None:
        return Metric(value=None, unit="ratio")
    if eps <= 0:
        return Metric(value=None, unit="ratio", reason=REASON_PE_NEGATIVE_EPS)
    return Metric(value=float(close / eps), unit="ratio")


def build_ps(close: Decimal | None, revenue: Decimal | None, shares: Decimal | None) -> Metric:
    """Trailing P/S cell (ratio) = close / (revenue / shares). None if any input missing/zero."""
    if close is None or revenue is None or shares is None or revenue == 0 or shares == 0:
        return Metric(value=None, unit="ratio")
    return Metric(value=float(close * shares / revenue), unit="ratio")
