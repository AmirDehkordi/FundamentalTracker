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


def test_duration_filter_rejects_non_annual_entries() -> None:
    # Rejects a ~90-day quarterly (lower bound) AND a ~725-day biennial (upper bound), each at its
    # own period_end so its rejection is observable; only the true 364-day annual survives.
    revenue = _by_year(xbrl.extract_annual_facts(_load("quarterly_reject")), "revenue")
    assert set(revenue) == {2023}
    assert revenue[2023].value == Decimal("383285000000")


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


def test_zero_placeholder_tag_yields_to_real_value() -> None:
    # ETN-shaped: higher-priority Revenues=0 is a placeholder; the real value is on SalesRevenueNet.
    revenue = _by_year(xbrl.extract_annual_facts(_load("tag_priority")), "revenue")
    assert revenue[2015].value == Decimal("20000")
    assert revenue[2015].source_tag == "us-gaap:SalesRevenueNet"


def test_tag_priority_wins_when_both_tags_report_a_year() -> None:
    # FY2016 sits on BOTH tags with different non-zero values; the higher-priority chain tag wins.
    revenue = _by_year(xbrl.extract_annual_facts(_load("tag_priority")), "revenue")
    assert revenue[2016].value == Decimal("96000")
    assert revenue[2016].source_tag == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def test_direct_tag_not_overwritten_by_derivation() -> None:
    # A directly-reported GrossProfit/OperatingIncomeLoss must survive as-is, never recomputed.
    facts = xbrl.extract_annual_facts(_load("direct_tags"))
    gross_profit = _by_year(facts, "gross_profit")[2022]
    assert gross_profit.source_tag == "us-gaap:GrossProfit"
    assert gross_profit.value == Decimal("145")  # reported 145, not revenue-cost = 150
    operating_income = _by_year(facts, "operating_income")[2022]
    assert operating_income.source_tag == "us-gaap:OperatingIncomeLoss"
    assert operating_income.value == Decimal("90")


def test_derived_row_provenance_is_latest_filed_input() -> None:
    facts = xbrl.extract_annual_facts(_load("derivation_provenance"))
    gross_profit = _by_year(facts, "gross_profit")[2022]
    assert gross_profit.value == Decimal("150")
    assert gross_profit.accession == "COST-ACCN"  # cost (filed 2023-08-15) is later than revenue
    assert gross_profit.filed == date(2023, 8, 15)


def test_malformed_entries_skipped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        revenue = _by_year(xbrl.extract_annual_facts(_load("malformed")), "revenue")
    assert set(revenue) == {2022}  # only the well-formed entry survives
    assert revenue[2022].value == Decimal("400")
    assert caplog.text.count("skipping malformed") >= 2  # missing val + missing accn both warned


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


def test_dedupe_captures_restatement_that_persists_across_comparatives() -> None:
    # 90 restated to 95, then 95 re-affirmed as a comparative in a later 10-K. The 90->95 change
    # must stay visible even though the immediately-prior filing merely repeats 95 (the aged shape).
    winner, superseded_value, superseded_filed = xbrl._dedupe(
        [
            _entry("90", date(2023, 11, 3)),
            _entry("95", date(2024, 11, 1)),
            _entry("95", date(2025, 11, 1)),
        ]
    )
    assert winner.val == Decimal("95")
    assert (superseded_value, superseded_filed) == (Decimal("90"), date(2023, 11, 3))


def test_dedupe_no_superseded_when_value_never_changed() -> None:
    # Same value in every filing -> genuinely no restatement.
    winner, superseded_value, superseded_filed = xbrl._dedupe(
        [_entry("95", date(2024, 11, 1)), _entry("95", date(2025, 11, 1))]
    )
    assert winner.val == Decimal("95")
    assert superseded_value is None and superseded_filed is None


def test_dedupe_uses_latest_filed_regardless_of_input_order() -> None:
    # companyfacts is not guaranteed filed-sorted; the winner must be max(filed), not the last item.
    winner, superseded_value, superseded_filed = xbrl._dedupe(
        [
            _entry("92", date(2024, 11, 1)),
            _entry("95", date(2025, 11, 1)),  # latest filed, listed in the middle
            _entry("90", date(2023, 11, 3)),
        ]
    )
    assert winner.val == Decimal("95")
    assert (superseded_value, superseded_filed) == (Decimal("92"), date(2024, 11, 1))


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
def test_load_ticker_map_skips_malformed_row(caplog: pytest.LogCaptureFixture) -> None:
    body = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"ticker": "NVDA"},  # malformed: NVDA is requested but the row has no cik_str
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=body))
        with caplog.at_level("WARNING"):
            result = xbrl.load_ticker_map(["AAPL", "NVDA"])
    assert result == {"AAPL": (320193, "Apple Inc.")}  # good row parsed, malformed one skipped
    assert "malformed" in caplog.text


@pytest.mark.usefixtures("client_env")
def test_fetch_companyfacts_hits_zero_padded_cik_url() -> None:
    url = xbrl.COMPANYFACTS_URL.format(cik=320193)
    assert "CIK0000320193.json" in url
    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200, json={"cik": 320193}))
        assert xbrl.fetch_companyfacts(320193) == {"cik": 320193}
        assert route.called
