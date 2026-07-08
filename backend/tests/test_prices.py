"""Price tests: yfinance DataFrame normalisation (MultiIndex/NaN), stooq CSV parsing, the yfinance
-> stooq fallback (on both raise and empty-frame), and the canonical cache round-trip."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx

from tracker.ingestion import edgar_client, prices

_STOOQ_CSV = (Path(__file__).parent / "fixtures" / "stooq" / "aapl.csv").read_text()
_STOOQ_AAPL = prices.STOOQ_URL.format(ticker_lower="aapl")


@pytest.fixture
def bronze_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(edgar_client, "BRONZE_DIR", tmp_path / "bronze")
    return tmp_path / "bronze"


def _yf_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-07-08", "2024-07-09", "2024-07-10"])
    return pd.DataFrame(
        {
            "Open": [150.0, 151.0, float("nan")],  # third row NaN -> dropped
            "High": [152.0, 153.0, 154.0],
            "Low": [149.0, 150.0, 151.0],
            "Close": [151.5, 152.5, 153.5],
            "Volume": [1_000_000, 1_100_000, 1_200_000],
        },
        index=idx,
    )


def test_parse_yf_dataframe_drops_nan_and_quantizes() -> None:
    rows = prices.parse_yf_dataframe(_yf_frame(), 320193, "AAPL")
    assert len(rows) == 2  # NaN row dropped
    assert rows[0].date == date(2024, 7, 8)
    assert rows[0].open_ == Decimal("150.000000") and rows[0].close == Decimal("151.500000")
    assert rows[0].volume == 1_000_000
    assert all(r.source == "yfinance" for r in rows)


def test_parse_yf_dataframe_flattens_multiindex_columns() -> None:
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    df = pd.DataFrame(
        [[150.0, 152.0, 149.0, 151.5, 1_000_000]],
        index=pd.to_datetime(["2024-07-08"]),
        columns=cols,
    )
    rows = prices.parse_yf_dataframe(df, 1, "AAPL")
    assert len(rows) == 1 and rows[0].open_ == Decimal("150.000000")


def test_parse_yf_dataframe_empty_or_none() -> None:
    assert prices.parse_yf_dataframe(pd.DataFrame(), 1, "AAPL") == []
    assert prices.parse_yf_dataframe(None, 1, "AAPL") == []


def test_parse_stooq_csv() -> None:
    rows = prices.parse_stooq_csv(_STOOQ_CSV, 320193, "AAPL")
    assert len(rows) == 3
    assert rows[0].close == Decimal("226.340000") and rows[0].source == "stooq"
    assert rows[2].date == date(2024, 7, 10)


def test_parse_stooq_csv_no_data_returns_empty() -> None:
    assert prices.parse_stooq_csv("No data", 1, "AAPL") == []


@pytest.mark.usefixtures("bronze_tmp")
def test_fetch_prices_falls_back_to_stooq_when_yfinance_raises() -> None:
    def _raiser(_ticker: str) -> pd.DataFrame:
        raise RuntimeError("yfinance is down")

    with respx.mock:
        respx.get(_STOOQ_AAPL).mock(return_value=httpx.Response(200, text=_STOOQ_CSV))
        rows = prices.fetch_prices(320193, "AAPL", downloader=_raiser)
    assert rows and all(r.source == "stooq" for r in rows)  # fell back to stooq


@pytest.mark.usefixtures("bronze_tmp")
def test_fetch_prices_falls_back_when_yfinance_returns_empty_frame() -> None:
    with respx.mock:
        respx.get(_STOOQ_AAPL).mock(return_value=httpx.Response(200, text=_STOOQ_CSV))
        rows = prices.fetch_prices(320193, "AAPL", downloader=lambda _t: pd.DataFrame())
    assert rows and all(r.source == "stooq" for r in rows)  # empty df is a failure too


@pytest.mark.usefixtures("bronze_tmp")
def test_fetch_prices_returns_empty_when_both_providers_fail() -> None:
    def _raiser(_ticker: str) -> pd.DataFrame:
        raise RuntimeError("yfinance is down")

    with respx.mock:
        respx.get(_STOOQ_AAPL).mock(return_value=httpx.Response(500))
        rows = prices.fetch_prices(320193, "AAPL", downloader=_raiser)
    assert rows == []  # yfinance raised, stooq 500 -> no data, no crash


@pytest.mark.usefixtures("bronze_tmp")
def test_fetch_prices_caches_and_replays_from_cache() -> None:
    with respx.mock:
        respx.get(_STOOQ_AAPL).mock(return_value=httpx.Response(200, text=_STOOQ_CSV))
        live = prices.fetch_prices(320193, "AAPL", downloader=lambda _t: pd.DataFrame())
    assert live  # a live run wrote the canonical cache

    # --from-cache replays the same rows with zero network (no respx routes registered).
    replayed = prices.fetch_prices(320193, "AAPL", from_cache=True)
    assert [r.model_dump(by_alias=True) for r in replayed] == [
        r.model_dump(by_alias=True) for r in live
    ]
    assert all(r.source == "stooq" for r in replayed)  # per-row source survived the round-trip


@pytest.mark.usefixtures("bronze_tmp")
def test_fetch_prices_from_cache_missing_file_is_skipped() -> None:
    assert prices.fetch_prices(1, "ZZZZ", from_cache=True) == []  # warn + skip, never raise


def test_cache_round_trip_supplies_caller_cik(bronze_tmp: Path) -> None:  # noqa: ARG001
    row = prices.PriceRow(
        cik=320193,
        date=date(2024, 7, 8),
        open_=Decimal("150.000000"),
        high=Decimal("152.000000"),
        low=Decimal("149.000000"),
        close=Decimal("151.500000"),
        volume=1_000_000,
        source="yfinance",
    )
    prices.write_cache_csv("AAPL", [row])
    back = prices.read_cache_csv(999, "AAPL")  # cache is ticker-scoped; cik supplied by caller
    assert len(back) == 1 and back[0].cik == 999 and back[0].open_ == Decimal("150.000000")
