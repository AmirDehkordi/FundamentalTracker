"""Prices: a daily OHLCV window + 10-K filing markers for the price chart (PLAN.md §9).

Pure read over prices/filings. The window is measured back from the latest stored trading date
(never "today", per the freshness policy). Mirrors schemas.PricesOut so P5 maps via model_validate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker.db.models import Company, Filing, Price

# range key -> lookback days, measured from the latest stored trading date. "3y" is the fetch window
# the chart uses (2y displayed + ~1y of history so the 150-day MA overlay is defined from the first
# visible day); the UI never labels a "3y" button.
_RANGE_DAYS = {"1m": 31, "6m": 183, "1y": 366, "2y": 731, "3y": 1096}
_DEFAULT_RANGE = "2y"


@dataclass(frozen=True, slots=True)
class PriceRowData:
    """Mirrors schemas.PriceRow."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


@dataclass(frozen=True, slots=True)
class FilingMarkerData:
    """Mirrors schemas.FilingMarker — a 10-K reference line on the chart."""

    accession: str
    form: str
    fiscal_year: int
    period_end: date
    filed: date
    primary_doc_url: str


@dataclass(frozen=True, slots=True)
class PricesResult:
    """Mirrors schemas.PricesOut."""

    ticker: str
    cik: int
    range: str
    rows: list[PriceRowData]
    filings: list[FilingMarkerData]


def latest_close_map(session: Session) -> dict[int, tuple[Decimal, date]]:
    """Latest stored close + its trading date per company, resolved independently, in one query.

    GROUP BY + join (not a Postgres-only DISTINCT ON) so this stays portable to SQLite unit tests,
    matching fiscal.latest_reported_fiscal_year_map's approach.
    """
    latest_dates = (
        select(Price.cik, func.max(Price.date).label("max_date")).group_by(Price.cik).subquery()
    )
    rows = session.execute(
        select(Price.cik, Price.date, Price.close).join(
            latest_dates,
            (Price.cik == latest_dates.c.cik) & (Price.date == latest_dates.c.max_date),
        )
    ).all()
    return {cik: (close, d) for cik, d, close in rows}


def get_prices(session: Session, ticker: str, range_: str = _DEFAULT_RANGE) -> PricesResult | None:
    """OHLCV within `range_` of the latest stored date + 10-K markers. None only for unknown ticker.

    A known company with no prices returns rows=[] (still carrying its filing markers) — an empty
    chart, not a missing resource. An unrecognised range falls back to the 2y default.
    """
    company = session.scalars(select(Company).where(Company.ticker == ticker.upper())).one_or_none()
    if company is None:
        return None
    range_key = range_ if range_ in _RANGE_DAYS else _DEFAULT_RANGE

    latest: date | None = session.scalar(
        select(Price.date).where(Price.cik == company.cik).order_by(Price.date.desc()).limit(1)
    )
    rows: list[PriceRowData] = []
    if latest is not None:
        start = latest - timedelta(days=_RANGE_DAYS[range_key])
        price_rows = session.scalars(
            select(Price).where(Price.cik == company.cik, Price.date >= start).order_by(Price.date)
        ).all()
        rows = [
            PriceRowData(
                date=p.date,
                open=float(p.open_),
                high=float(p.high),
                low=float(p.low),
                close=float(p.close),
                volume=p.volume,
                source=p.source,
            )
            for p in price_rows
        ]

    markers = session.scalars(
        select(Filing)
        .where(Filing.cik == company.cik, Filing.form == "10-K")
        .order_by(Filing.filed)
    ).all()
    filings = [
        FilingMarkerData(
            accession=f.accession,
            form=f.form,
            fiscal_year=f.fiscal_year,
            period_end=f.period_end,
            filed=f.filed,
            primary_doc_url=f.primary_doc_url,
        )
        for f in markers
    ]
    return PricesResult(
        ticker=company.ticker, cik=company.cik, range=range_key, rows=rows, filings=filings
    )
