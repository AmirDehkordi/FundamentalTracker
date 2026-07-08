"""Pure metric functions + the shared MetricValue-shaped cell (PLAN.md §6).

Two layers live here. The *scalar* functions (`gross_margin`, `yoy`, `operating_leverage`, …) are
pure math: they take `Decimal | None` off the ORM, do all arithmetic in `Decimal` (exact guards for
the 1%-of-revenue and sign tests), return `float | None`, and NEVER raise on bad data. The *builder*
functions (`build_pe`, `build_yoy`, …) wrap a scalar into a `Metric` and attach the correct
None-with-reason string. Reason selection sits beside the guards, so a caller never misreads a
`None` (a bare `float | None` can't say which of operating leverage's three guards tripped).

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
MetricUnit = Literal["USD", "USD/shares", "shares", "percent", "ratio"]


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
# Operating leverage: PLAN.md §6 flags all three causes "n.m."; each keeps the specific cause.
REASON_OPLEV_REVENUE_DECLINED = "n.m. — revenue declined"
REASON_OPLEV_REVENUE_FLAT = "n.m. — revenue change < 1%"
REASON_OPLEV_OPINC_SIGN_FLIP = "n.m. — operating income changed sign"

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


def _oplev_reason(
    oi_curr: Decimal, oi_prev: Decimal, rev_curr: Decimal, rev_prev: Decimal
) -> str | None:
    """Which operating-leverage guard trips (deterministic priority), or None if it holds."""
    delta_rev = rev_curr - rev_prev
    if delta_rev < 0:
        return REASON_OPLEV_REVENUE_DECLINED
    # Flat/blow-up: |ΔRev| < 1% of revenue. `delta_rev == 0` is caught here too (both revenues zero
    # slips past the 1% test since the threshold is also 0) so the division below can never be by 0.
    if delta_rev == 0 or abs(delta_rev) < abs(rev_curr) / 100:
        return REASON_OPLEV_REVENUE_FLAT
    if oi_curr * oi_prev < 0:  # operating income flipped sign — incremental margin is meaningless
        return REASON_OPLEV_OPINC_SIGN_FLIP
    return None


def operating_leverage(
    op_income_curr: Decimal | None,
    op_income_prev: Decimal | None,
    revenue_curr: Decimal | None,
    revenue_prev: Decimal | None,
) -> float | None:
    """ΔOperatingIncome / ΔRevenue, FY over FY. None if an input is missing or a guard trips."""
    if (
        op_income_curr is None
        or op_income_prev is None
        or revenue_curr is None
        or revenue_prev is None
    ):
        return None
    if _oplev_reason(op_income_curr, op_income_prev, revenue_curr, revenue_prev) is not None:
        return None
    return float((op_income_curr - op_income_prev) / (revenue_curr - revenue_prev))


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


def build_operating_leverage(
    op_income_curr: Decimal | None,
    op_income_prev: Decimal | None,
    revenue_curr: Decimal | None,
    revenue_prev: Decimal | None,
) -> Metric:
    """Operating-leverage cell (ratio). Missing input → None; else the tripped-guard reason."""
    value = operating_leverage(op_income_curr, op_income_prev, revenue_curr, revenue_prev)
    if value is not None:
        return Metric(value=value, unit="ratio")
    if (
        op_income_curr is None
        or op_income_prev is None
        or revenue_curr is None
        or revenue_prev is None
    ):
        return Metric(value=None, unit="ratio")
    reason = _oplev_reason(op_income_curr, op_income_prev, revenue_curr, revenue_prev)
    return Metric(value=None, unit="ratio", reason=reason)


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
