"""Runner tests: dialect-aware upsert (idempotency + restatement) and an end-to-end run on SQLite.

The upsert runs the same on_conflict_do_update the Postgres path uses, so the natural-key
restatement behaviour is verified without a database service. The end-to-end test drives run_xbrl
over respx-mocked EDGAR into an in-memory SQLite session.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
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

from tracker.db.models import Base, Company, Fundamental
from tracker.ingestion import edgar_client, runner, xbrl
from tracker.ingestion.__main__ import main
from tracker.ingestion.xbrl import FundamentalFact

_DERIVATIONS = Path(__file__).parent / "fixtures" / "companyfacts" / "derivations.json"

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
