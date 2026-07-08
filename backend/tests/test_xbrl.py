"""XBRL extraction tests over committed companyfacts-shaped fixtures (no network).

Covers the messy-data core: per-year tag fallback, latest-filed-wins + superseded capture, the
FY-duration filter, gross_profit/operating_income derivation, and the fiscal_year = period_end.year
rule (the entry's own `fy` is deliberately ignored — see the xbrl module docstring).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from tracker.ingestion import edgar_client, xbrl

_FIXTURES = Path(__file__).parent / "fixtures" / "companyfacts"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_FIXTURES / f"{name}.json").read_text())
    return data


def _by_year(facts: list[xbrl.FundamentalFact], concept: str) -> dict[int, xbrl.FundamentalFact]:
    return {f.fiscal_year: f for f in facts if f.concept == concept}


def test_revenue_falls_back_to_second_tag_per_year() -> None:
    revenue = _by_year(xbrl.extract_annual_facts(_load("revenue_fallback")), "revenue")
    # FY2023 lives on the first tag; FY2024 only on the second -> per-year fallback (GOOGL trap).
    assert revenue[2023].source_tag == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue[2024].source_tag == "us-gaap:Revenues"


def test_fiscal_year_is_period_end_year_not_entry_fy() -> None:
    # FY2022 revenue appears as a comparative inside a 2024-filed 10-K carrying fy=2024; it must be
    # labelled FY2022 from period_end (finance/Bloomberg convention), never from the entry's fy.
    revenue = _by_year(xbrl.extract_annual_facts(_load("revenue_fallback")), "revenue")
    assert revenue[2022].period_end == date(2022, 9, 24)
    assert revenue[2022].fiscal_year == 2022


def test_latest_filed_wins_and_captures_superseded() -> None:
    fact = _by_year(xbrl.extract_annual_facts(_load("restatement")), "net_income")[2023]
    assert fact.value == Decimal("95000000000")
    assert fact.filed == date(2024, 11, 1)
    assert fact.superseded_value == Decimal("90000000000")
    assert fact.superseded_filed == date(2023, 11, 3)


def test_duration_filter_rejects_quarterly_entry() -> None:
    facts = xbrl.extract_annual_facts(_load("quarterly_reject"))
    revenue = [f for f in facts if f.concept == "revenue"]
    assert len(revenue) == 1  # the ~90-day fp=FY quarterly entry is dropped
    assert revenue[0].value == Decimal("383285000000")


def test_gross_profit_derived_when_missing() -> None:
    gross_profit = _by_year(xbrl.extract_annual_facts(_load("derivations")), "gross_profit")
    assert gross_profit[2023].value == Decimal("170000000000")
    assert gross_profit[2023].source_tag == "derived:revenue-cost_of_revenue"
    assert gross_profit[2022].value == Decimal("150000000000")


def test_operating_income_derived_and_skipped_when_component_missing() -> None:
    operating_income = _by_year(xbrl.extract_annual_facts(_load("derivations")), "operating_income")
    assert operating_income[2023].value == Decimal("115000000000")
    assert operating_income[2023].source_tag == "derived:revenue-cost_of_revenue-sga-rnd"
    assert 2022 not in operating_income  # FY2022 lacks rnd -> not derivable, skipped with a log


def test_derivation_inputs_stored_and_per_share_units_preserved() -> None:
    facts = xbrl.extract_annual_facts(_load("derivations"))
    assert _by_year(facts, "eps_diluted")[2023].unit == "USD/shares"
    assert _by_year(facts, "shares_diluted")[2023].unit == "shares"
    assert 2023 in _by_year(facts, "sga")  # sga/rnd persist as rows purely to feed operating_income


def _entry(val: str, filed: date) -> xbrl._Entry:
    return xbrl._Entry(
        end=date(2023, 9, 30),
        start=date(2022, 10, 1),
        val=Decimal(val),
        accn=f"a-{filed}",
        filed=filed,
        form="10-K",
        tag="NetIncomeLoss",
    )


def test_dedupe_captures_immediately_prior_distinct_value() -> None:
    # Three filings, increasing value: winner is latest-filed; superseded is the value it replaced.
    winner, superseded_value, superseded_filed = xbrl._dedupe(
        [
            _entry("90", date(2023, 11, 3)),
            _entry("92", date(2024, 11, 1)),
            _entry("95", date(2025, 11, 1)),
        ]
    )
    assert winner.val == Decimal("95")
    assert (superseded_value, superseded_filed) == (Decimal("92"), date(2024, 11, 1))


def test_dedupe_no_superseded_when_latest_repeats_value() -> None:
    # Latest filing re-reports the prior value unchanged -> nothing was restated.
    winner, superseded_value, superseded_filed = xbrl._dedupe(
        [
            _entry("90", date(2023, 11, 3)),
            _entry("95", date(2024, 11, 1)),
            _entry("95", date(2025, 11, 1)),
        ]
    )
    assert winner.val == Decimal("95")
    assert superseded_value is None and superseded_filed is None


@pytest.fixture
def client_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the shared client for network-facing xbrl helpers: tmp bronze, stubbed settings."""
    monkeypatch.setattr(edgar_client, "BRONZE_DIR", tmp_path / "bronze")
    monkeypatch.setattr(edgar_client, "from_cache", False)
    monkeypatch.setattr(edgar_client, "_client", None)
    monkeypatch.setattr(edgar_client, "_last_request_ts", None)
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        edgar_client,
        "get_settings",
        lambda: SimpleNamespace(sec_user_agent="Test test@example.com (tests)"),
    )


@pytest.mark.usefixtures("client_env")
def test_load_ticker_map_filters_universe_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    body = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corporation"},
        "2": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=body))
        with caplog.at_level("WARNING"):
            result = xbrl.load_ticker_map(["AAPL", "NVDA", "ZZZZ"])
    assert result == {"AAPL": (320193, "Apple Inc."), "NVDA": (1045810, "NVIDIA Corporation")}
    assert "ZZZZ" in caplog.text  # missing ticker warned, never silently dropped


@pytest.mark.usefixtures("client_env")
def test_fetch_companyfacts_hits_zero_padded_cik_url() -> None:
    url = xbrl.COMPANYFACTS_URL.format(cik=320193)
    assert "CIK0000320193.json" in url
    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200, json={"cik": 320193}))
        assert xbrl.fetch_companyfacts(320193) == {"cik": 320193}
        assert route.called
