"""End-to-end API over real Postgres (mini_seed): every endpoint + error path on the true dialect.

Marked `integration`, so excluded from `make verify` and skipped unless TEST_DATABASE_URL is set.
Proves the routers work against Postgres (NUMERIC round-trip, tsv/GIN schema) — not the coverage
gate, which the SQLite suite carries. Values match mini_seed (AAPL/NVDA, FY2023-2025, 3 concepts).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tracker.api.app import create_app
from tracker.db.session import get_session

pytestmark = pytest.mark.integration


def _client(session: Session) -> TestClient:
    app = create_app()

    def _override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def test_health(pg_session: Session) -> None:
    resp = _client(pg_session).get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_companies(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies")
    assert resp.status_code == 200
    assert [c["ticker"] for c in resp.json()] == ["AAPL", "NVDA"]


def test_fundamentals(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies/AAPL/fundamentals")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["fiscal_year"] for r in body["rows"]] == [2023, 2024, 2025]
    assert body["rows"][-1]["metrics"]["revenue"]["value"] == 3e11


def test_fundamentals_unknown_404(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/companies/ZZZZ/fundamentals").status_code == 404


def test_prices(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies/AAPL/prices?range=1y")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "1y"
    assert len(body["rows"]) == 30
    assert len(body["filings"]) == 3


def test_prices_unknown_404(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/companies/ZZZZ/prices").status_code == 404


def test_valuation(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies/AAPL/valuation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trailing_pe"]["value"] == pytest.approx(179 / 7)
    assert body["trailing_ps"]["value"] is None
    assert body["price_as_of"] == "2026-06-30"


def test_valuation_unknown_404(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/companies/ZZZZ/valuation").status_code == 404


def test_risk_diff(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies/AAPL/risk-diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False  # only one year of Item 1A chunks in mini_seed
    assert body["latest"]["fiscal_year"] == 2025


def test_risk_diff_unknown_404(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/companies/ZZZZ/risk-diff").status_code == 404


def test_insider(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/companies/AAPL/insider")
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False


def test_insider_unknown_404(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/companies/ZZZZ/insider").status_code == 404


def test_compare(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/compare?metric=revenue_yoy")
    assert resp.status_code == 200
    aapl = next(row for row in resp.json()["rows"] if row["ticker"] == "AAPL")
    assert aapl["value"]["value"] == 0.5
    assert aapl["value"]["unit"] == "percent"


def test_compare_bad_metric_422(pg_session: Session) -> None:
    assert _client(pg_session).get("/api/compare?metric=bogus").status_code == 422


def test_freshness(pg_session: Session) -> None:
    resp = _client(pg_session).get("/api/meta/freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_count"] == 2
    assert body["source_counts"] == {"yfinance": 60, "fundamentals": 18}
