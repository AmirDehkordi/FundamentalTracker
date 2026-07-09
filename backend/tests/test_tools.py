"""Agent tool handlers (agent/tools.py): direct calls against seeded SQLite, no LLM, no network."""

from __future__ import annotations

import datetime
from typing import get_args

import pytest
from sqlalchemy.orm import Session

from tracker.agent import tools
from tracker.concepts import CANONICAL_CONCEPTS
from tracker.db.models import Company
from tracker.services.fundamentals import DERIVED_UNITS


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # _unknown_ticker reads get_settings().universe_tickers, so the settings must be constructable.
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@test.co (t)")
    from tracker.config import get_settings

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# get_fundamentals — filtering the service does not do
# ---------------------------------------------------------------------------


def test_get_fundamentals_last_n_and_concept_subset(rich_session: Session) -> None:
    out = tools.get_fundamentals(
        rich_session,
        tools.GetFundamentalsArgs(
            ticker="full", concepts=["revenue", "operating_margin"], last_n_years=2
        ),
    )
    assert out["ok"] is True
    assert len(out["rows"]) == 2
    latest = out["rows"][-1]
    assert latest["fiscal_year"] == 2025
    assert set(latest["metrics"]) == {"revenue", "operating_margin"}
    # yoy is subset by the SAME keys; operating_margin is not a yoy key, revenue is.
    assert set(latest["yoy"]) == {"revenue"}
    assert latest["metrics"]["operating_margin"]["value"] == pytest.approx(0.325)
    assert latest["label"] == "FY2025 (ended 2025-12-31)"


def test_get_fundamentals_ignores_unknown_concept(rich_session: Session) -> None:
    out = tools.get_fundamentals(
        rich_session, tools.GetFundamentalsArgs(ticker="FULL", concepts=["revenue", "bogus"])
    )
    assert out["ignored_concepts"] == ["bogus"]
    assert set(out["rows"][-1]["metrics"]) == {"revenue"}


def test_get_fundamentals_none_with_reason_and_restatement(rich_session: Session) -> None:
    out = tools.get_fundamentals(rich_session, tools.GetFundamentalsArgs(ticker="EDGE"))
    by_fy = {row["fiscal_year"]: row for row in out["rows"]}
    # net income <= 0 -> fcf_conversion is None-with-reason, carried through _metric_dict.
    fcf_conv = by_fy[2025]["metrics"]["fcf_conversion"]
    assert fcf_conv["value"] is None
    assert fcf_conv["reason"]
    # Restated FY2023 revenue keeps the superseded value visible.
    revenue_2023 = by_fy[2023]["metrics"]["revenue"]
    assert revenue_2023["superseded_value"] == pytest.approx(105_000_000_000.0)
    assert revenue_2023["superseded_filed"] == "2023-03-01"


def test_get_fundamentals_unknown_ticker(db_session: Session) -> None:
    out = tools.get_fundamentals(db_session, tools.GetFundamentalsArgs(ticker="ZZZZ"))
    assert out == {
        "ok": False,
        "error": "unknown_ticker",
        "ticker": "ZZZZ",
        "in_universe": False,
        "detail": "No tracked data for ZZZZ.",
    }


# ---------------------------------------------------------------------------
# compare_companies
# ---------------------------------------------------------------------------


def test_compare_raw_and_derived(db_session: Session) -> None:
    raw = tools.compare_companies(db_session, tools.CompareCompaniesArgs(metric="revenue"))
    assert raw["metric"] == "revenue"
    assert [r["ticker"] for r in raw["rows"]] == ["AAPL", "NVDA"]
    assert raw["rows"][0]["value"]["value"] == pytest.approx(300_000_000_000.0)
    assert raw["rows"][0]["fiscal_year"] == 2025  # each cell footnotes its own FY
    assert raw["basis_note"]

    derived = tools.compare_companies(db_session, tools.CompareCompaniesArgs(metric="revenue_yoy"))
    assert derived["rows"][0]["value"]["unit"] == "percent"


# ---------------------------------------------------------------------------
# get_valuation — happy, n.m. P/E, and whole-result None
# ---------------------------------------------------------------------------


def test_valuation_happy(db_session: Session) -> None:
    out = tools.get_valuation(db_session, tools.GetValuationArgs(ticker="AAPL"))
    assert out["ok"] is True
    assert out["trailing_pe"]["value"] == pytest.approx(179 / 7)
    assert out["trailing_ps"]["value"] is None  # mini_seed has no shares_diluted
    assert out["eps_source"]["label"] == "FY2025 (ended 2025-09-27)"
    assert out["eps_source"]["accession"] == "0000320193-2025-10K"


def test_valuation_nm_pe(rich_session: Session) -> None:
    out = tools.get_valuation(rich_session, tools.GetValuationArgs(ticker="EDGE"))
    assert out["trailing_pe"]["value"] is None
    assert out["trailing_pe"]["reason"] == "n.m. — negative EPS"


def test_valuation_no_price_or_fy(db_session: Session) -> None:
    db_session.add(Company(cik=999999, ticker="ZZZ", name="Zed Co."))
    db_session.commit()
    out = tools.get_valuation(db_session, tools.GetValuationArgs(ticker="ZZZ"))
    assert out == {
        "ok": False,
        "error": "no_valuation",
        "ticker": "ZZZ",
        "detail": "No trailing multiples: missing stored price or reported fiscal year.",
    }


# ---------------------------------------------------------------------------
# search_filings — hits and first-class empty
# ---------------------------------------------------------------------------


def test_search_filings_hits(db_session: Session) -> None:
    out = tools.search_filings(
        db_session, tools.SearchFilingsArgs(ticker="AAPL", query="supply", item="1A")
    )
    assert out["count"] >= 1
    hit = out["hits"][0]
    assert hit["accession"] == "0000320193-2025-10K"
    assert hit["item"] == "1A"
    assert hit["url"].startswith("https://www.sec.gov/")


def test_search_filings_empty_is_not_error(db_session: Session) -> None:
    out = tools.search_filings(
        db_session, tools.SearchFilingsArgs(ticker="AAPL", query="zzznomatchxyz")
    )
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["hits"] == []


# ---------------------------------------------------------------------------
# diff_risk_factors — degraded (only one FY of 1A in mini_seed)
# ---------------------------------------------------------------------------


def test_risk_diff_degraded(db_session: Session) -> None:
    out = tools.diff_risk_factors(db_session, tools.DiffRiskFactorsArgs(ticker="AAPL"))
    assert out["available"] is False
    assert out["note"]
    assert out["prior"] is None
    assert out["latest"] is not None
    assert out["latest"]["accession"] == "0000320193-2025-10K"


# ---------------------------------------------------------------------------
# get_insider_activity — no Form 4 rows in mini_seed
# ---------------------------------------------------------------------------


def test_insider_no_data(db_session: Session) -> None:
    out = tools.get_insider_activity(db_session, tools.GetInsiderActivityArgs(ticker="NVDA"))
    assert out["has_data"] is False
    assert out["caveat"]
    assert out["window_90d"]["buy_count"] == 0
    assert out["window_365d"]["sell_count"] == 0


# ---------------------------------------------------------------------------
# list_universe
# ---------------------------------------------------------------------------


def test_list_universe(db_session: Session) -> None:
    out = tools.list_universe(db_session, tools.ListUniverseArgs())
    assert [c["ticker"] for c in out["companies"]] == ["AAPL", "NVDA"]
    aapl = out["companies"][0]
    assert aapl["latest_fiscal_year"] == 2025
    assert aapl["latest_fy_label"] == "FY2025 (ended 2025-09-27)"
    assert aapl["latest_period_end"] == "2025-09-27"


# ---------------------------------------------------------------------------
# dispatch: call_tool + schema generation
# ---------------------------------------------------------------------------


def test_call_tool_validation_error(db_session: Session) -> None:
    out = tools.call_tool(db_session, "compare_companies", '{"metric": "bogus"}')
    assert out["ok"] is False
    assert out["error"] == "invalid_arguments"


def test_call_tool_unknown_tool(db_session: Session) -> None:
    out = tools.call_tool(db_session, "nope", "{}")
    assert out["error"] == "unknown_tool"


def test_call_tool_happy_dispatch(db_session: Session) -> None:
    out = tools.call_tool(db_session, "list_universe", "")  # empty args string -> {}
    assert out["ok"] is True
    assert len(out["companies"]) == 2


def test_call_tool_handler_exception_is_surfaced(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_session: Session, _args: object) -> dict[str, object]:
        raise RuntimeError("kaboom")

    monkeypatch.setitem(
        tools.TOOLS,
        "list_universe",
        tools.ToolSpec("list_universe", "x", tools.ListUniverseArgs, _boom),
    )
    out = tools.call_tool(db_session, "list_universe", "{}")
    assert out["error"] == "tool_failed"
    assert "kaboom" in out["detail"]


def test_openai_tools_schema_shape() -> None:
    schema = tools.openai_tools_schema()
    assert len(schema) == 7
    for entry in schema:
        params = entry["function"]["parameters"]
        assert params["type"] == "object"
        assert "$defs" not in params  # flat args models -> inline schema, safe as OpenAI parameters
        assert entry["function"]["description"]


def test_compare_metric_enum_matches_frozen_vocab() -> None:
    # The hand-spelled Literal must never drift from the service's supported set.
    assert set(get_args(tools.CompareMetric)) == CANONICAL_CONCEPTS | frozenset(DERIVED_UNITS)


def test_unknown_ticker_short_circuits_all_ticker_tools(db_session: Session) -> None:
    assert (
        tools.get_valuation(db_session, tools.GetValuationArgs(ticker="NOPE"))["error"]
        == "unknown_ticker"
    )
    assert (
        tools.search_filings(db_session, tools.SearchFilingsArgs(ticker="NOPE", query="x"))["error"]
        == "unknown_ticker"
    )
    assert (
        tools.diff_risk_factors(db_session, tools.DiffRiskFactorsArgs(ticker="NOPE"))["error"]
        == "unknown_ticker"
    )
    assert (
        tools.get_insider_activity(db_session, tools.GetInsiderActivityArgs(ticker="NOPE"))["error"]
        == "unknown_ticker"
    )


def test_summarize_covers_every_tool(db_session: Session) -> None:
    def _s(name: str, raw_args: str) -> str:
        return tools.summarize(name, tools.call_tool(db_session, name, raw_args))

    assert "FY rows" in _s("get_fundamentals", '{"ticker": "AAPL"}')
    assert "P/E" in _s("get_valuation", '{"ticker": "AAPL"}')
    assert "companies" in _s("compare_companies", '{"metric": "revenue"}')
    assert "hits" in _s("search_filings", '{"ticker": "AAPL", "query": "supply"}')
    assert "1A" in _s("diff_risk_factors", '{"ticker": "AAPL"}')
    assert "has_data" in _s("get_insider_activity", '{"ticker": "NVDA"}')
    assert "2 companies" in _s("list_universe", "{}")
    err = tools.call_tool(db_session, "compare_companies", '{"metric": "bogus"}')
    assert "invalid_arguments" in tools.summarize("compare_companies", err)
    assert tools.summarize("mystery", {"ok": True}) == "mystery ok"  # fallback


def test_every_tool_payload_is_json_serializable(db_session: Session) -> None:
    # Invariant 4: loop.py does json.dumps(result) on every tool result, so no Decimal/date/other
    # non-JSON object may leak from any handler. Cover all 7 (db_session has AAPL + NVDA).
    import json

    cases = [
        ("get_fundamentals", '{"ticker": "AAPL"}'),
        ("compare_companies", '{"metric": "fcf_conversion"}'),
        ("get_valuation", '{"ticker": "AAPL"}'),
        ("search_filings", '{"ticker": "AAPL", "query": "supply"}'),
        ("diff_risk_factors", '{"ticker": "AAPL"}'),
        ("get_insider_activity", '{"ticker": "NVDA"}'),
        ("list_universe", "{}"),
    ]
    for name, raw in cases:
        json.dumps(tools.call_tool(db_session, name, raw))  # must not raise


def test_get_fundamentals_empty_concepts_returns_all(rich_session: Session) -> None:
    # An explicit concepts=[] means 'no filter', same as omitting it — never all-empty rows.
    out = tools.get_fundamentals(
        rich_session, tools.GetFundamentalsArgs(ticker="FULL", concepts=[])
    )
    assert out["ignored_concepts"] == []
    assert len(out["rows"][-1]["metrics"]) > 1


def test_fiscal_serializer_isoformats_dates() -> None:
    out = tools._fiscal("FY2025 (ended 2025-09-27)", 2025, datetime.date(2025, 9, 27))
    assert out == {
        "label": "FY2025 (ended 2025-09-27)",
        "fiscal_year": 2025,
        "period_end": "2025-09-27",
    }
