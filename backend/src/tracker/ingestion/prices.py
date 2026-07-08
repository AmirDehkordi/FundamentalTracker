"""Daily prices: yfinance with a stooq fallback (sec-edgar skill §Prices).

Per ticker: yfinance download (2y, daily, auto-adjusted). On ANY failure — an exception OR an empty
frame (yfinance often returns df.empty instead of raising) — fall back to the stooq CSV endpoint and
record the source per row. The per-ticker cache is a NORMALISED canonical CSV
(date,open,high,low,close,volume,source), deliberately a *silver* cache rather than raw bronze:
yfinance hands back a DataFrame (no faithful raw bytes exist) and the per-row source must survive an
offline --from-cache replay, which then runs the same upsert with zero provider-shape branching.
Decimals are quantised to the column scale so a value is identical on SQLite (tests) and Postgres.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, ConfigDict, Field

from tracker.ingestion import edgar_client

logger = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker_lower}.us&i=d"

_PRICE_Q = Decimal("0.000001")  # matches Price.open/high/low/close NUMERIC(18, 6)
_CACHE_HEADER = ("date", "open", "high", "low", "close", "volume", "source")
_OHLC = ("Open", "High", "Low", "Close")


class PriceRow(BaseModel):
    """One daily OHLCV bar for `prices`; model_dump(by_alias=True) yields the SQL column names."""

    model_config = ConfigDict(populate_by_name=True)

    cik: int
    date: date
    open_: Decimal = Field(alias="open")  # SQL column is "open"; attr avoids shadowing the builtin
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str  # yfinance | stooq


def _q_price(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_PRICE_Q)


def _cache_path(ticker: str) -> Path:
    # Reference BRONZE_DIR at call time so a test monkeypatch of it also redirects the price cache.
    return edgar_client.BRONZE_DIR / f"prices_{ticker}.csv"


def parse_yf_dataframe(df: Any, cik: int, ticker: str) -> list[PriceRow]:
    """Normalise a yfinance download into PriceRows (empty/NaN handled, MultiIndex flattened)."""
    if df is None or getattr(df, "empty", True):
        return []
    frame = df.copy()
    if isinstance(frame.columns, pd.MultiIndex):  # single-ticker downloads can be (field, ticker)
        frame.columns = frame.columns.get_level_values(0)
    frame = frame[~frame.index.duplicated(keep="last")]

    rows: list[PriceRow] = []
    for idx, row in frame.iterrows():
        values = [row.get(col) for col in (*_OHLC, "Volume")]
        if any(pd.isna(v) for v in values):  # holidays / partial rows
            continue
        o, h, lo, c, vol = values
        rows.append(
            PriceRow(
                cik=cik,
                date=idx.date() if hasattr(idx, "date") else idx,
                open_=_q_price(o),
                high=_q_price(h),
                low=_q_price(lo),
                close=_q_price(c),
                volume=int(round(float(vol))),
                source="yfinance",
            )
        )
    return rows


def parse_stooq_csv(text: str, cik: int, ticker: str) -> list[PriceRow]:
    """Parse a stooq daily CSV into PriceRows; a non-CSV body ("No data"/error) yields []."""
    body = text.strip()
    if not body.lower().startswith("date,"):  # stooq returns a plain message on failure, not a 4xx
        logger.warning("stooq returned no usable CSV for %s", ticker)
        return []
    rows: list[PriceRow] = []
    for record in csv.DictReader(io.StringIO(body)):
        try:
            rows.append(
                PriceRow(
                    cik=cik,
                    date=date.fromisoformat(record["Date"]),
                    open_=_q_price(record["Open"]),
                    high=_q_price(record["High"]),
                    low=_q_price(record["Low"]),
                    close=_q_price(record["Close"]),
                    volume=int(round(float(record["Volume"]))),
                    source="stooq",
                )
            )
        except (KeyError, ValueError, InvalidOperation) as exc:
            logger.warning("skipping malformed stooq row for %s: %s", ticker, exc)
    return rows


def write_cache_csv(ticker: str, rows: list[PriceRow]) -> None:
    """Write the canonical price CSV atomically (a truncated cache would poison --from-cache)."""
    path = _cache_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CACHE_HEADER)
    for r in rows:
        writer.writerow([r.date.isoformat(), r.open_, r.high, r.low, r.close, r.volume, r.source])
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(buffer.getvalue())
    tmp.replace(path)


def read_cache_csv(cik: int, ticker: str) -> list[PriceRow]:
    """Read the canonical price CSV back into PriceRows (cik is ticker-scoped, from the caller)."""
    rows: list[PriceRow] = []
    for record in csv.DictReader(io.StringIO(_cache_path(ticker).read_text())):
        rows.append(
            PriceRow(
                cik=cik,
                date=date.fromisoformat(record["date"]),
                open_=Decimal(record["open"]),
                high=Decimal(record["high"]),
                low=Decimal(record["low"]),
                close=Decimal(record["close"]),
                volume=int(record["volume"]),
                source=record["source"],
            )
        )
    return rows


def _yf_download(ticker: str) -> Any:
    return yf.download(ticker, period="2y", interval="1d", auto_adjust=True, progress=False)


def _fetch_stooq(cik: int, ticker: str) -> list[PriceRow]:
    url = STOOQ_URL.format(ticker_lower=ticker.lower())
    try:
        response = httpx.get(url, timeout=30.0, headers={"User-Agent": "fundamentals-tracker"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("stooq fetch failed for %s: %s", ticker, exc)
        return []
    return parse_stooq_csv(response.text, cik, ticker)


def fetch_prices(
    cik: int,
    ticker: str,
    from_cache: bool = False,
    downloader: Callable[[str], Any] | None = None,
) -> list[PriceRow]:
    """2y daily prices for one ticker: yfinance, else stooq; cached to a canonical CSV."""
    if from_cache:
        if not _cache_path(ticker).exists():
            logger.warning("--from-cache: no price cache for %s; skipping ticker", ticker)
            return []
        return read_cache_csv(cik, ticker)

    download = downloader or _yf_download
    try:
        rows = parse_yf_dataframe(download(ticker), cik, ticker)
    except Exception as exc:  # yfinance surfaces many transient/library errors — never crash a run
        logger.warning("yfinance failed for %s: %s", ticker, exc)
        rows = []
    if not rows:  # covers both the exception path and yfinance's silent empty-frame return
        logger.info("falling back to stooq for %s (yfinance returned no data)", ticker)
        rows = _fetch_stooq(cik, ticker)
    if rows:
        write_cache_csv(ticker, rows)
    return rows
