"""Insider activity: Form 4 buy/sell summary over trailing windows (PLAN.md §13).

Windows anchor to the company's most recent Form 4 filing date — never `datetime.now`, so the
summary is deterministic and never implies "today". Counts include unpriced rows (the trade still
happened); notional sums use priced rows only. A standing 10b5-1 caveat rides on every summary, so
the signal is not oversold as sentiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import Company, InsiderTransaction

INSIDER_CAVEAT = (
    "Counts include Rule 10b5-1 pre-scheduled trades, which are arranged in advance and are not "
    "necessarily a directional signal."
)


@dataclass(frozen=True, slots=True)
class InsiderWindowData:
    """Mirrors schemas.InsiderWindow."""

    days: int
    buy_count: int
    sell_count: int
    net_shares: float | None
    net_notional: float | None
    buy_notional: float | None = None
    sell_notional: float | None = None


@dataclass(frozen=True, slots=True)
class InsiderSummaryResult:
    """Mirrors schemas.InsiderSummaryOut."""

    ticker: str
    cik: int
    window_90d: InsiderWindowData
    window_365d: InsiderWindowData
    caveat: str
    has_data: bool


def summary(session: Session, cik: int, *, as_of: date | None = None) -> InsiderSummaryResult:
    """90d/365d buy/sell counts + net notional. `as_of` overrides the anchor; else max filed."""
    company = session.get(Company, cik)
    ticker = company.ticker if company is not None else ""
    rows = list(
        session.scalars(select(InsiderTransaction).where(InsiderTransaction.cik == cik)).all()
    )
    if not rows:
        return InsiderSummaryResult(
            ticker=ticker,
            cik=cik,
            window_90d=_empty_window(90),
            window_365d=_empty_window(365),
            caveat=INSIDER_CAVEAT,
            has_data=False,
        )
    anchor = as_of if as_of is not None else max(row.filed for row in rows)
    return InsiderSummaryResult(
        ticker=ticker,
        cik=cik,
        window_90d=_window(rows, 90, anchor),
        window_365d=_window(rows, 365, anchor),
        caveat=INSIDER_CAVEAT,
        has_data=True,
    )


def _empty_window(days: int) -> InsiderWindowData:
    return InsiderWindowData(
        days=days,
        buy_count=0,
        sell_count=0,
        net_shares=None,
        net_notional=None,
        buy_notional=None,
        sell_notional=None,
    )


def _window(rows: list[InsiderTransaction], days: int, anchor: date) -> InsiderWindowData:
    start = anchor - timedelta(days=days)
    in_window = [row for row in rows if start <= row.filed <= anchor]  # inclusive both ends
    if not in_window:
        return _empty_window(days)
    buys = [row for row in in_window if row.code == "P"]
    sells = [row for row in in_window if row.code == "S"]
    net_shares = sum((b.shares for b in buys), Decimal(0)) - sum(
        (s.shares for s in sells), Decimal(0)
    )
    return InsiderWindowData(
        days=days,
        buy_count=len(buys),  # counts include unpriced (null-value) rows
        sell_count=len(sells),
        net_shares=float(net_shares),
        net_notional=_net_notional(buys, sells),
        buy_notional=_sum_notional(buys),
        sell_notional=_sum_notional(sells),
    )


def _sum_notional(txns: list[InsiderTransaction]) -> float | None:
    priced = [t.value for t in txns if t.value is not None]
    if not priced:
        return None
    return float(sum(priced, Decimal(0)))


def _net_notional(buys: list[InsiderTransaction], sells: list[InsiderTransaction]) -> float | None:
    priced_buys = [b.value for b in buys if b.value is not None]
    priced_sells = [s.value for s in sells if s.value is not None]
    if not priced_buys and not priced_sells:
        return None
    return float(sum(priced_buys, Decimal(0)) - sum(priced_sells, Decimal(0)))
