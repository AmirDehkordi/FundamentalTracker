"""End-to-end API over real Postgres (mini_seed): every endpoint + error path on the true dialect.

Marked `integration`, so excluded from `make verify` and skipped unless TEST_DATABASE_URL is set.
Proves the routers work against Postgres (NUMERIC round-trip, tsv/GIN schema) — not the coverage
gate, which the SQLite suite carries. Values match mini_seed (AAPL/NVDA, FY2023-2025, 3 concepts).
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tracker.api.app import create_app
from tracker.db.session import get_session

pytestmark = pytest.mark.integration

_SEED_DUMP = Path(__file__).parents[2] / "seed" / "init" / "01_seed.sql.gz"


def _seed_copy_rows(sql: str, table: str) -> list[dict[str, str]]:
    """Rows of one table's COPY block in a pg_dump, as {column: raw-text} dicts."""
    match = re.search(
        rf"^COPY public\.{table} \(([^)]+)\) FROM stdin;\n(.*?)^\\\.$",
        sql,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"no COPY block for {table} in the seed dump"
    columns = [c.strip() for c in match.group(1).split(",")]
    return [
        dict(zip(columns, line.split("\t"), strict=True))
        for line in match.group(2).splitlines()
        if line
    ]


def test_committed_seed_pins_acceptance_values() -> None:
    """The two planning-time acceptance values, asserted against the committed seed itself:
    the GOOGL FY2025 tag switch to bare `Revenues` and the NVDA split restatement with the
    pre-split figure retained (PLAN.md §10 chunk 2)."""
    sql = gzip.decompress(_SEED_DUMP.read_bytes()).decode()
    rows = _seed_copy_rows(sql, "fundamentals")

    googl_rev = next(
        r
        for r in rows
        if r["cik"] == "1652044" and r["concept"] == "revenue" and r["fiscal_year"] == "2025"
    )
    assert Decimal(googl_rev["value"]) == Decimal("402836000000")
    assert googl_rev["source_tag"] == "us-gaap:Revenues"

    nvda_eps = next(
        r
        for r in rows
        if r["cik"] == "1045810" and r["concept"] == "eps_diluted" and r["fiscal_year"] == "2024"
    )
    assert Decimal(nvda_eps["value"]) == Decimal("1.19")
    assert Decimal(nvda_eps["superseded_value"]) == Decimal("11.93")


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
