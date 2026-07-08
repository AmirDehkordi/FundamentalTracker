"""Runner tests: dialect-aware upsert (idempotency + restatement) and an end-to-end run on SQLite.

The upsert runs the same on_conflict_do_update the Postgres path uses, so the natural-key
restatement behaviour is verified without a database service. The end-to-end test drives run_xbrl
over respx-mocked EDGAR into an in-memory SQLite session.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tracker.db.models import (
    Base,
    Company,
    Filing,
    FilingChunk,
    Fundamental,
    InsiderTransaction,
    Price,
)
from tracker.ingestion import edgar_client, filings, form4, prices, runner, submissions, xbrl
from tracker.ingestion.__main__ import main
from tracker.ingestion.xbrl import FundamentalFact

_DERIVATIONS = Path(__file__).parent / "fixtures" / "companyfacts" / "derivations.json"
_TENK_HTML = (Path(__file__).parent / "fixtures" / "tenk" / "toc_and_sections.html").read_text()
_AAPL_SUBMISSIONS = (Path(__file__).parent / "fixtures" / "submissions" / "aapl.json").read_text()

_BASE_FACT = FundamentalFact(
    cik=320193,
    concept="revenue",
    source_tag="us-gaap:Revenues",
    fiscal_year=2023,
    period_start=date(2022, 10, 1),
    period_end=date(2023, 9, 30),
    value=Decimal("380000000000"),
    unit="USD",
    accession="A-2023",
    filed=date(2023, 11, 3),
    form="10-K",
)


def _fact(**overrides: Any) -> FundamentalFact:
    return _BASE_FACT.model_copy(update=overrides)


def _minimal_companyfacts(cik: int, revenue: int) -> dict[str, Any]:
    return {
        "cik": cik,
        "entityName": f"Entity {cik}",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2022-10-01",
                                "end": "2023-09-30",
                                "val": revenue,
                                "accn": f"{cik:010d}-23-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                            }
                        ]
                    }
                }
            }
        },
    }


@pytest.fixture
def empty_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_upsert_is_idempotent_and_applies_restatement(empty_session: Session) -> None:
    runner._upsert_company(empty_session, 320193, "AAPL", "Apple Inc.")
    runner._upsert_fundamentals(empty_session, [_fact()])
    runner._upsert_fundamentals(empty_session, [_fact()])  # re-ingest same key -> no duplicate
    empty_session.commit()
    rows = empty_session.execute(select(Fundamental)).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == Decimal("380000000000")

    runner._upsert_fundamentals(
        empty_session,
        [
            _fact(
                value=Decimal("385000000000"),
                superseded_value=Decimal("380000000000"),
                superseded_filed=date(2023, 11, 3),
                filed=date(2024, 11, 1),
                accession="A-2024",
            )
        ],
    )
    empty_session.commit()
    rows = empty_session.execute(select(Fundamental)).scalars().all()
    assert len(rows) == 1  # same natural key updated in place
    assert rows[0].value == Decimal("385000000000")
    assert rows[0].superseded_value == Decimal("380000000000")


@pytest.mark.usefixtures("client_env")
def test_run_xbrl_end_to_end_on_sqlite(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(_DERIVATIONS.read_text())

    @contextmanager
    def _scope() -> Iterator[Session]:
        yield empty_session
        empty_session.commit()

    monkeypatch.setattr(runner, "session_scope", _scope)
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL"]))

    tickers_body = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(xbrl.COMPANYFACTS_URL.format(cik=320193)).mock(
            return_value=httpx.Response(200, json=payload)
        )
        summaries = runner.run_xbrl(from_cache=False)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.ticker == "AAPL"
    assert summary.latest_fy == 2023
    assert (
        summary.latest_fy_label == "FY2023 (ended 2023-09-30)"
    )  # ended-date carried, per CLAUDE.md
    assert summary.latest_revenue == Decimal("380000000000")
    assert "Archives/edgar/data/320193" in summary.accession_url

    assert empty_session.get(Company, 320193) is not None
    gross_profit = (
        empty_session.execute(select(Fundamental).where(Fundamental.concept == "gross_profit"))
        .scalars()
        .all()
    )
    assert gross_profit and gross_profit[0].value == Decimal("170000000000")

    runner.print_summary(summaries)
    assert "AAPL" in capsys.readouterr().out


def test_cli_dispatches_xbrl_with_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[bool] = []
    monkeypatch.setattr(runner, "run_xbrl", lambda from_cache: recorded.append(from_cache) or [])
    assert main(["--sources", "xbrl", "--from-cache"]) == 0
    assert recorded == [True]


def test_cli_rejects_unknown_source() -> None:
    with pytest.raises(SystemExit):  # argparse.error exits non-zero
        main(["--sources", "bogus"])


@pytest.mark.usefixtures("client_env")
def test_run_xbrl_isolates_a_failing_company(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A per-company DB error must be skipped, not crash the run, and must not leave a partial row
    # for the failing company nor discard the company that succeeded (savepoint isolation).
    good_cik, bad_cik = 111, 222

    @contextmanager
    def _scope() -> Iterator[Session]:
        yield empty_session
        empty_session.commit()

    monkeypatch.setattr(runner, "session_scope", _scope)
    monkeypatch.setattr(
        runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["GOOD", "BAD"])
    )

    real_upsert = runner._upsert_fundamentals

    def _flaky(session: Session, facts: list[FundamentalFact]) -> None:
        if facts and facts[0].cik == bad_cik:
            raise RuntimeError("simulated DB write failure")
        real_upsert(session, facts)

    monkeypatch.setattr(runner, "_upsert_fundamentals", _flaky)

    tickers_body = {
        "0": {"cik_str": good_cik, "ticker": "GOOD", "title": "Good Inc."},
        "1": {"cik_str": bad_cik, "ticker": "BAD", "title": "Bad Inc."},
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(xbrl.COMPANYFACTS_URL.format(cik=good_cik)).mock(
            return_value=httpx.Response(200, json=_minimal_companyfacts(good_cik, 100))
        )
        respx.get(xbrl.COMPANYFACTS_URL.format(cik=bad_cik)).mock(
            return_value=httpx.Response(200, json=_minimal_companyfacts(bad_cik, 200))
        )
        summaries = runner.run_xbrl(from_cache=False)

    assert [s.ticker for s in summaries] == ["GOOD"]  # bad company skipped, run survived
    assert empty_session.get(Company, good_cik) is not None
    assert empty_session.get(Company, bad_cik) is None  # savepoint rolled back the partial write
    good_rows = empty_session.execute(
        select(Fundamental).where(Fundamental.cik == good_cik)
    ).first()
    assert good_rows is not None


@pytest.mark.usefixtures("client_env")
def test_run_xbrl_survives_missing_ticker_and_empty_facts(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def _scope() -> Iterator[Session]:
        yield empty_session
        empty_session.commit()

    monkeypatch.setattr(runner, "session_scope", _scope)
    monkeypatch.setattr(
        runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL", "GHOST"])
    )
    # GHOST is absent from company_tickers; AAPL resolves but returns zero annual facts.
    tickers_body = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    empty_facts = {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": {}}}
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(xbrl.COMPANYFACTS_URL.format(cik=320193)).mock(
            return_value=httpx.Response(200, json=empty_facts)
        )
        summaries = runner.run_xbrl(from_cache=False)

    assert [s.ticker for s in summaries] == ["AAPL"]  # GHOST skipped, run survived
    summary = summaries[0]
    assert summary.latest_fy is None
    assert summary.latest_fy_label == "-"  # degenerate labels render cleanly
    assert summary.accession_url == "-"
    assert empty_session.get(Company, 320193) is not None


# --------------------------------------------------------------------------------------------------
# Filings lane
# --------------------------------------------------------------------------------------------------


def _filing_row(**overrides: Any) -> filings.FilingRow:
    base = dict(
        accession="0000320193-24-000123",
        cik=320193,
        form="10-K",
        fiscal_year=2024,
        period_end=date(2024, 9, 28),
        filed=date(2024, 11, 1),
        primary_doc_url="https://example.test/doc.htm",
    )
    base.update(overrides)
    return filings.FilingRow(**base)  # type: ignore[arg-type]


def _chunk_row(index: int, text: str, item: str = "1A") -> filings.ChunkRow:
    return filings.ChunkRow(
        accession="0000320193-24-000123",
        cik=320193,
        item=item,
        fiscal_year=2024,
        chunk_index=index,
        text=text,
    )


def test_upsert_filings_is_idempotent_and_updates_in_place(empty_session: Session) -> None:
    runner._upsert_company(empty_session, 320193, "AAPL", "Apple Inc.")
    runner._upsert_filings(empty_session, [_filing_row()])
    runner._upsert_filings(empty_session, [_filing_row(primary_doc_url="https://example.test/v2")])
    empty_session.commit()
    rows = empty_session.execute(select(Filing)).scalars().all()
    assert len(rows) == 1  # same accession PK updated, not duplicated
    assert rows[0].primary_doc_url == "https://example.test/v2"


def test_replace_filing_chunks_removes_orphans_on_reingest(empty_session: Session) -> None:
    # A re-ingest yielding FEWER chunks must not leave orphaned high-index rows.
    runner._upsert_company(empty_session, 320193, "AAPL", "Apple Inc.")
    runner._upsert_filings(empty_session, [_filing_row()])
    runner._replace_filing_chunks(empty_session, [_chunk_row(i, f"first-{i}") for i in range(3)])
    empty_session.commit()
    assert len(empty_session.execute(select(FilingChunk)).scalars().all()) == 3

    runner._replace_filing_chunks(empty_session, [_chunk_row(i, f"second-{i}") for i in range(2)])
    empty_session.commit()
    remaining = empty_session.execute(select(FilingChunk)).scalars().all()
    assert {r.chunk_index for r in remaining} == {0, 1}  # index 2 orphan deleted
    assert all(r.text.startswith("second-") for r in remaining)  # content replaced


def _filings_scope(session: Session) -> Any:
    @contextmanager
    def _scope() -> Iterator[Session]:
        yield session
        session.commit()

    return _scope


@pytest.mark.usefixtures("client_env")
def test_run_filings_end_to_end_on_sqlite(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL"]))

    tickers_body = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(submissions.SUBMISSIONS_URL.format(cik=320193)).mock(
            return_value=httpx.Response(200, text=_AAPL_SUBMISSIONS)
        )
        for nodash, doc in (
            ("000032019324000123", "aapl-20240928.htm"),
            ("000032019323000106", "aapl-20230930.htm"),
        ):
            respx.get(filings.ARCHIVES_DOC_URL.format(cik=320193, nodash=nodash, doc=doc)).mock(
                return_value=httpx.Response(200, text=_TENK_HTML)
            )
        summaries = runner.run_filings(from_cache=False)

    assert len(summaries) == 1
    s = summaries[0]
    assert s.ticker == "AAPL"
    assert {item for item, _fy, _c in s.chunk_counts} == {"1A", "7"}  # both sections extracted
    assert {fy for _i, fy, _c in s.chunk_counts} == {2023, 2024}  # both 10-Ks

    filing_rows = empty_session.execute(select(Filing)).scalars().all()
    assert {f.accession for f in filing_rows} == {"0000320193-24-000123", "0000320193-23-000106"}
    chunk_rows = empty_session.execute(select(FilingChunk)).scalars().all()
    assert chunk_rows and all(c.item in {"1A", "7"} for c in chunk_rows)
    assert empty_session.get(Company, 320193) is not None

    runner.print_filings_summary(summaries)
    assert "AAPL" in capsys.readouterr().out


@pytest.mark.usefixtures("client_env")
def test_run_filings_survives_a_failing_company(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A company whose submissions 404s is skipped; the healthy company still ingests.
    good_cik, bad_cik = 320193, 999999
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(
        runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL", "BAD"])
    )

    tickers_body = {
        "0": {"cik_str": good_cik, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": bad_cik, "ticker": "BAD", "title": "Bad Inc."},
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(submissions.SUBMISSIONS_URL.format(cik=good_cik)).mock(
            return_value=httpx.Response(200, text=_AAPL_SUBMISSIONS)
        )
        respx.get(submissions.SUBMISSIONS_URL.format(cik=bad_cik)).mock(
            return_value=httpx.Response(404)
        )
        for nodash, doc in (
            ("000032019324000123", "aapl-20240928.htm"),
            ("000032019323000106", "aapl-20230930.htm"),
        ):
            respx.get(filings.ARCHIVES_DOC_URL.format(cik=good_cik, nodash=nodash, doc=doc)).mock(
                return_value=httpx.Response(200, text=_TENK_HTML)
            )
        summaries = runner.run_filings(from_cache=False)

    assert [s.ticker for s in summaries] == ["AAPL"]  # BAD skipped, run survived
    assert empty_session.get(Company, bad_cik) is None


def test_print_filings_summary_handles_empty_counts(capsys: pytest.CaptureFixture[str]) -> None:
    runner.print_filings_summary([runner.FilingSummary(ticker="ZZZ", cik=1, chunk_counts=())])
    assert "ZZZ" in capsys.readouterr().out  # degenerate row renders cleanly


# --------------------------------------------------------------------------------------------------
# Form 4 lane
# --------------------------------------------------------------------------------------------------


def _insider_txn(**overrides: Any) -> form4.InsiderTxn:
    base = dict(
        cik=320193,
        accession="0000320193-24-000070",
        filed=date(2024, 7, 15),
        insider_name="COOK TIMOTHY D",
        role="Chief Executive Officer",
        code="P",
        shares=Decimal("1000.0000"),
        price=Decimal("150.000000"),
        value=Decimal("150000.000000"),
    )
    base.update(overrides)
    return form4.InsiderTxn(**base)  # type: ignore[arg-type]


def test_upsert_insiders_is_idempotent_and_updates_non_key_columns(empty_session: Session) -> None:
    runner._upsert_company(empty_session, 320193, "AAPL", "Apple Inc.")
    runner._upsert_insiders(empty_session, [_insider_txn()])
    runner._upsert_insiders(empty_session, [_insider_txn(role="CEO", value=Decimal("150001.0"))])
    empty_session.commit()
    rows = empty_session.execute(select(InsiderTransaction)).scalars().all()
    assert len(rows) == 1  # same natural key updated in place, not duplicated
    assert rows[0].role == "CEO"


def _recent_form4_submissions() -> str:
    # A Form 4 filed 5 days ago so it is always inside run_form4's 12-month window.
    recent = (date.today() - timedelta(days=5)).isoformat()
    payload = {
        "cik": 320193,
        "filings": {
            "recent": {
                "form": ["4", "10-K"],
                "accessionNumber": ["0000320193-24-000070", "0000320193-24-000123"],
                "primaryDocument": ["xslF345X05/wk-form4.xml", "aapl-20240928.htm"],
                "filingDate": [recent, "2024-11-01"],
                "reportDate": ["2024-07-13", "2024-09-28"],
            }
        },
    }
    return json.dumps(payload)


@pytest.mark.usefixtures("client_env")
def test_run_form4_end_to_end_on_sqlite(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL"]))

    xml = (Path(__file__).parent / "fixtures" / "form4" / "buy_and_sale.xml").read_bytes()
    tickers_body = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(submissions.SUBMISSIONS_URL.format(cik=320193)).mock(
            return_value=httpx.Response(200, text=_recent_form4_submissions())
        )
        respx.get(
            filings.ARCHIVES_DOC_URL.format(
                cik=320193, nodash="000032019324000070", doc="wk-form4.xml"
            )
        ).mock(return_value=httpx.Response(200, content=xml))
        summaries = runner.run_form4(from_cache=False)

    assert len(summaries) == 1
    assert (summaries[0].buys, summaries[0].sells) == (2, 1)  # two P rows, one S row

    rows = empty_session.execute(select(InsiderTransaction)).scalars().all()
    assert {r.code for r in rows} == {"P", "S"}
    assert any(r.price is None for r in rows)  # the footnote-only row landed with NULL price
    assert empty_session.get(Company, 320193) is not None

    runner.print_form4_summary(summaries)
    assert "AAPL" in capsys.readouterr().out


@pytest.mark.usefixtures("client_env")
def test_run_form4_survives_a_failing_company(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(
        runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL", "BAD"])
    )
    xml = (Path(__file__).parent / "fixtures" / "form4" / "buy_and_sale.xml").read_bytes()
    tickers_body = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 999999, "ticker": "BAD", "title": "Bad Inc."},
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        respx.get(submissions.SUBMISSIONS_URL.format(cik=320193)).mock(
            return_value=httpx.Response(200, text=_recent_form4_submissions())
        )
        respx.get(submissions.SUBMISSIONS_URL.format(cik=999999)).mock(
            return_value=httpx.Response(500)
        )
        respx.get(
            filings.ARCHIVES_DOC_URL.format(
                cik=320193, nodash="000032019324000070", doc="wk-form4.xml"
            )
        ).mock(return_value=httpx.Response(200, content=xml))
        summaries = runner.run_form4(from_cache=False)

    assert [s.ticker for s in summaries] == ["AAPL"]  # BAD skipped, run survived
    assert empty_session.get(Company, 999999) is None


def _price_row(**overrides: Any) -> prices.PriceRow:
    base = dict(
        cik=320193,
        date=date(2024, 7, 8),
        open_=Decimal("150.000000"),
        high=Decimal("152.000000"),
        low=Decimal("149.000000"),
        close=Decimal("151.500000"),
        volume=1_000_000,
        source="yfinance",
    )
    base.update(overrides)
    return prices.PriceRow(**base)  # type: ignore[arg-type]


def test_upsert_prices_idempotent_and_flips_source(empty_session: Session) -> None:
    runner._upsert_company(empty_session, 320193, "AAPL", "Apple Inc.")
    runner._upsert_prices(empty_session, [_price_row()])
    runner._upsert_prices(empty_session, [_price_row(source="stooq", close=Decimal("151.600000"))])
    empty_session.commit()
    rows = empty_session.execute(select(Price)).scalars().all()
    assert len(rows) == 1  # same (cik, date) natural key updated in place
    assert rows[0].source == "stooq" and rows[0].close == Decimal("151.600000")


@pytest.mark.usefixtures("client_env")
def test_run_prices_end_to_end_on_sqlite(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL"]))
    # Stub the provider fetch so no yfinance/network is touched; exercise the upsert + summary.
    monkeypatch.setattr(
        runner.prices, "fetch_prices", lambda cik, ticker, from_cache: [_price_row()]
    )

    tickers_body = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        summaries = runner.run_prices(from_cache=False)

    assert len(summaries) == 1
    assert summaries[0].rows == 1 and summaries[0].source == "yfinance"
    rows = empty_session.execute(select(Price)).scalars().all()
    assert len(rows) == 1
    # Cross-dialect scale: the quantized Decimal round-trips identically on SQLite.
    assert rows[0].open_ == Decimal("150.000000") and rows[0].close == Decimal("151.500000")
    assert empty_session.get(Company, 320193) is not None

    runner.print_prices_summary(summaries)
    assert "AAPL" in capsys.readouterr().out


def test_summarize_prices_reports_source_or_mixed() -> None:
    assert runner._summarize_prices("AAPL", 1, []).source == "-"
    assert runner._summarize_prices("AAPL", 1, [_price_row()]).source == "yfinance"
    mixed = [_price_row(), _price_row(date=date(2024, 7, 9), source="stooq")]
    assert runner._summarize_prices("AAPL", 1, mixed).source == "mixed"


@pytest.mark.usefixtures("client_env")
def test_run_prices_survives_a_failing_company(
    empty_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "session_scope", _filings_scope(empty_session))
    monkeypatch.setattr(
        runner, "get_settings", lambda: SimpleNamespace(universe_tickers=["AAPL", "BAD"])
    )

    def _fetch(cik: int, ticker: str, from_cache: bool) -> list[prices.PriceRow]:
        if ticker == "BAD":
            raise RuntimeError("provider exploded")
        return [_price_row()]

    monkeypatch.setattr(runner.prices, "fetch_prices", _fetch)
    tickers_body = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 999999, "ticker": "BAD", "title": "Bad Inc."},
    }
    with respx.mock:
        respx.get(xbrl.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers_body))
        summaries = runner.run_prices(from_cache=False)

    assert [s.ticker for s in summaries] == ["AAPL"]  # BAD skipped, run survived
    assert empty_session.get(Company, 999999) is None


def test_cli_dispatches_all_sources_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    for name in ("xbrl", "filings", "form4", "prices"):
        monkeypatch.setattr(runner, f"run_{name}", lambda from_cache, n=name: calls.append(n) or [])
    for name in ("summary", "filings_summary", "form4_summary", "prices_summary"):
        monkeypatch.setattr(runner, f"print_{name}", lambda s: None)

    assert main(["--sources", "prices"]) == 0
    assert calls == ["prices"]

    calls.clear()
    assert main(["--sources", "all"]) == 0
    assert calls == [
        "xbrl",
        "filings",
        "form4",
        "prices",
    ]  # 'all' expands to every source, in order
