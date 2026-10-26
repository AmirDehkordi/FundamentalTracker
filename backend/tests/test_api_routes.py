"""Router behavior over SQLite (no Postgres): every endpoint + every error branch.

These are the coverage-bearing API tests — `make verify` runs `-m "not integration"`, so the
Postgres suite (test_api_integration.py) does not count toward the gate. Assertions target the
mini_seed universe (AAPL/NVDA, FY2023-2025, 3 concepts) unless a case seeds its own row.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tracker.api.app import create_app
from tracker.db.models import Company, Fundamental
from tracker.db.session import get_session
from tracker.services.fiscal import COMPARE_BASIS_NOTE
from tracker.services.metrics import BASIS_NOTE_PS_WAD


def _client(session: Session) -> TestClient:
    app = create_app()

    def _override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


# --- companies list --------------------------------------------------------------------------


def test_companies_lists_universe(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies")
    assert resp.status_code == 200
    assert [c["ticker"] for c in resp.json()] == ["AAPL", "NVDA"]


# --- fundamentals ----------------------------------------------------------------------------


def test_fundamentals_returns_labelled_rows(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/fundamentals")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["fiscal_year"] for r in body["rows"]] == [2023, 2024, 2025]
    last = body["rows"][-1]
    assert last["label"] == "FY2025 (ended 2025-09-27)"
    assert last["metrics"]["revenue"]["value"] == 3e11
    assert last["metrics"]["eps_diluted"]["value"] == 7
    assert last["metrics"]["gross_margin"]["value"] is None  # no gross_profit seeded
    assert last["yoy"]["revenue"]["value"] == 0.5  # 3e11 / 2e11 - 1


def test_fundamentals_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/ZZZZ/fundamentals")
    assert resp.status_code == 404
    assert "ZZZZ" in resp.json()["detail"]


def test_fundamentals_ticker_is_case_insensitive(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/aapl/fundamentals")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"


# --- prices ----------------------------------------------------------------------------------


def test_prices_default_range(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "2y"
    assert len(body["rows"]) == 30
    assert len(body["filings"]) == 3
    assert body["filings"][0]["primary_doc_url"].startswith("https://www.sec.gov/Archives/")


def test_prices_explicit_range(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/prices?range=1m")
    assert resp.status_code == 200
    assert resp.json()["range"] == "1m"


def test_prices_bad_range_falls_back_to_2y(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/prices?range=5y")
    assert resp.status_code == 200  # bad range is not an error; the service normalizes it
    assert resp.json()["range"] == "2y"


def test_prices_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/ZZZZ/prices")
    assert resp.status_code == 404


# --- valuation -------------------------------------------------------------------------------


def test_valuation_happy(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/valuation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trailing_pe"]["value"] == pytest.approx(179 / 7)  # close 179, eps 7
    assert body["trailing_ps"]["value"] is None  # no shares_diluted seeded
    assert body["close"] == 179.0
    assert body["price_as_of"] == "2026-06-30"
    assert body["eps_source"]["accession"] == "0000320193-2025-10K"
    assert body["basis_note"] == BASIS_NOTE_PS_WAD


def test_valuation_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/ZZZZ/valuation")
    assert resp.status_code == 404
    assert "ZZZZ" in resp.json()["detail"]


def test_valuation_known_ticker_without_price_404(db_session: Session) -> None:
    # A reported company (has a 10-K fact) but no stored price cannot form a ValuationOut.
    db_session.add(Company(cik=999999, ticker="NOPX", name="No Price Co."))
    db_session.add(
        Fundamental(
            cik=999999,
            concept="eps_diluted",
            source_tag="us-gaap:EarningsPerShareDiluted",
            fiscal_year=2025,
            period_start=datetime.date(2025, 1, 1),
            period_end=datetime.date(2025, 12, 31),
            value=Decimal("5"),
            unit="USD/shares",
            accession="0000999999-2025-10K",
            filed=datetime.date(2025, 3, 1),
            form="10-K",
        )
    )
    db_session.commit()
    resp = _client(db_session).get("/api/companies/NOPX/valuation")
    assert resp.status_code == 404
    assert "no stored price" in resp.json()["detail"]


# --- risk-diff -------------------------------------------------------------------------------


def test_risk_diff_degraded_single_year(db_session: Session) -> None:
    # Only AAPL FY2025 Item 1A chunks exist -> fewer than two years -> degraded but 200.
    resp = _client(db_session).get("/api/companies/AAPL/risk-diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["note"]
    assert body["latest"]["fiscal_year"] == 2025
    assert body["prior"] is None
    assert body["added"] == [] and body["removed"] == []
    assert body["counts"] == {"added": 0, "removed": 0, "unchanged": 0}


def test_risk_diff_no_chunks(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/NVDA/risk-diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["latest"] is None


def test_risk_diff_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/ZZZZ/risk-diff")
    assert resp.status_code == 404


# --- insider ---------------------------------------------------------------------------------


def test_insider_no_transactions(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/AAPL/insider")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_data"] is False
    assert body["window_90d"]["buy_count"] == 0
    assert body["window_90d"]["net_shares"] is None
    assert body["caveat"]


def test_insider_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session).get("/api/companies/ZZZZ/insider")
    assert resp.status_code == 404


# --- compare ---------------------------------------------------------------------------------


def test_compare_raw_concept(db_session: Session) -> None:
    resp = _client(db_session).get("/api/compare?metric=revenue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["basis_note"] == COMPARE_BASIS_NOTE
    assert [row["ticker"] for row in body["rows"]] == ["AAPL", "NVDA"]
    aapl = next(row for row in body["rows"] if row["ticker"] == "AAPL")
    assert aapl["value"]["value"] == 3e11
    assert aapl["label"] == "FY2025 (ended 2025-09-27)"


def test_compare_revenue_yoy(db_session: Session) -> None:
    resp = _client(db_session).get("/api/compare?metric=revenue_yoy")
    assert resp.status_code == 200
    aapl = next(row for row in resp.json()["rows"] if row["ticker"] == "AAPL")
    assert aapl["value"]["value"] == 0.5
    assert aapl["value"]["unit"] == "percent"


def test_compare_bad_metric_422(db_session: Session) -> None:
    resp = _client(db_session).get("/api/compare?metric=bogus")
    assert resp.status_code == 422
    assert "bogus" in resp.json()["detail"]


def test_compare_missing_metric_422(db_session: Session) -> None:
    resp = _client(db_session).get("/api/compare")
    assert resp.status_code == 422


# --- meta ------------------------------------------------------------------------------------


def test_freshness(db_session: Session) -> None:
    resp = _client(db_session).get("/api/meta/freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_price_date"] == "2026-06-30"
    assert body["max_filed_date"] == "2025-11-01"
    assert body["company_count"] == 2
    assert body["source_counts"] == {"yfinance": 60, "fundamentals": 18}
