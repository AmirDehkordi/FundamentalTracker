"""Form 4 buy/sell window summary (services/insider.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import InsiderTransaction
from tracker.services import insider

AAPL_CIK = 320193
NVDA_CIK = 1045810
ANCHOR = datetime.date(2026, 6, 30)
D = Decimal


def _add(
    session: Session,
    filed: datetime.date,
    code: str,
    shares: str,
    value: str | None,
    tag: str,
) -> None:
    session.add(
        InsiderTransaction(
            cik=AAPL_CIK,
            accession=f"f4-{tag}",
            filed=filed,
            insider_name="Jane Insider",
            role="CFO",
            code=code,
            shares=D(shares),
            price=None,
            value=None if value is None else D(value),
        )
    )


def test_no_data(db_session: Session) -> None:
    result = insider.summary(db_session, NVDA_CIK)
    assert result.has_data is False
    assert result.window_90d.buy_count == 0
    assert result.window_90d.net_shares is None
    assert result.caveat == insider.INSIDER_CAVEAT


def test_anchor_is_max_filed(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", "1000", "recent")
    _add(db_session, ANCHOR - datetime.timedelta(days=100), "S", "50", "500", "old")
    db_session.commit()
    result = insider.summary(db_session, AAPL_CIK)  # anchor = max filed = ANCHOR
    assert result.has_data is True
    assert result.window_90d.buy_count == 1 and result.window_90d.sell_count == 0
    assert result.window_365d.buy_count == 1 and result.window_365d.sell_count == 1


def test_counts_include_null_value_rows(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", "1000", "priced")
    _add(db_session, ANCHOR, "P", "200", None, "unpriced")
    db_session.commit()
    window = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR).window_90d
    assert window.buy_count == 2  # the unpriced row still counts
    assert window.buy_notional == 1000.0  # but only priced rows sum
    assert window.net_notional == 1000.0


def test_none_notional_when_none_priced(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", None, "a")
    _add(db_session, ANCHOR, "S", "40", None, "b")
    db_session.commit()
    window = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR).window_90d
    assert window.buy_count == 1 and window.sell_count == 1
    assert window.buy_notional is None
    assert window.sell_notional is None
    assert window.net_notional is None


def test_window_boundaries_inclusive(db_session: Session) -> None:
    _add(db_session, ANCHOR - datetime.timedelta(days=90), "P", "10", "1", "d90")
    _add(db_session, ANCHOR - datetime.timedelta(days=91), "P", "20", "2", "d91")
    _add(db_session, ANCHOR - datetime.timedelta(days=365), "P", "30", "3", "d365")
    _add(db_session, ANCHOR - datetime.timedelta(days=366), "P", "40", "4", "d366")
    db_session.commit()
    result = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR)
    assert result.window_90d.buy_count == 1  # d90 in, d91 out
    assert result.window_365d.buy_count == 3  # d90 + d91 + d365 in, d366 out


def test_windows_differ_when_data_spans_more_than_90_days(db_session: Session) -> None:
    # The UI showed identical 90d/365d for some tickers. That is CORRECT only when every Form 4
    # falls within 90 days of the max-filed anchor (MSFT/GOOGL/ETN in the seed). With data spanning
    # >90 days (as AAPL/NVDA do), the two windows MUST be computed over genuinely different sets.
    _add(db_session, ANCHOR, "P", "100", "1000", "recent-buy")  # in both windows
    _add(
        db_session, ANCHOR - datetime.timedelta(days=200), "S", "50", "500", "old-sell"
    )  # 365d only
    db_session.commit()
    result = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR)
    assert result.window_90d.buy_count == 1 and result.window_90d.sell_count == 0
    assert result.window_365d.buy_count == 1 and result.window_365d.sell_count == 1
    # Genuinely different windows: 365d captures the older sell that 90d excludes.
    assert result.window_90d.sell_count != result.window_365d.sell_count
    assert result.window_90d.net_shares != result.window_365d.net_shares  # 100 vs 50
    assert result.window_90d.sell_notional is None
    assert result.window_365d.sell_notional == 500.0


def test_empty_short_window(db_session: Session) -> None:
    _add(db_session, ANCHOR - datetime.timedelta(days=200), "P", "10", "1", "d200")
    db_session.commit()
    result = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR)
    assert result.window_90d.net_shares is None  # nothing in the 90-day window
    assert result.window_365d.buy_count == 1


def test_net_shares(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", "1", "buy")
    _add(db_session, ANCHOR, "S", "40", "1", "sell")
    db_session.commit()
    window = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR).window_90d
    assert window.net_shares == 60.0
    assert window.net_notional == 0.0  # 1 buy - 1 sell notional


def test_as_of_override(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", "1000", "recent")
    _add(db_session, ANCHOR - datetime.timedelta(days=100), "S", "50", "500", "old")
    db_session.commit()
    # Anchor at the older date: the recent row is in the future (filed > anchor) and excluded.
    result = insider.summary(db_session, AAPL_CIK, as_of=ANCHOR - datetime.timedelta(days=100))
    assert result.window_90d.sell_count == 1
    assert result.window_90d.buy_count == 0


def test_insider_maps_to_wire_schema(db_session: Session) -> None:
    _add(db_session, ANCHOR, "P", "100", "1000", "x")
    db_session.commit()
    result = insider.summary(db_session, AAPL_CIK)
    wire = schemas.InsiderSummaryOut.model_validate(result)
    assert wire.ticker == "AAPL"  # identity passthrough from the Company row
    assert wire.cik == AAPL_CIK
    assert wire.window_90d.buy_count == 1
    assert wire.caveat == insider.INSIDER_CAVEAT
    assert wire.has_data is True
