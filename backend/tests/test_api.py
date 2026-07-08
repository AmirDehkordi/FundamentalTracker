"""FastAPI factory (api/app.py): /health live, /api/companies reads DB, all routes wired."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tracker.api.app import create_app
from tracker.db.session import get_session


def test_health_returns_ok_with_versions() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "app" in body["versions"]
    assert "python" in body["versions"]


def test_companies_lists_seeded_universe(db_session: Session) -> None:
    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    client = TestClient(app)

    resp = client.get("/api/companies")
    assert resp.status_code == 200
    data = resp.json()
    assert [c["ticker"] for c in data] == ["AAPL", "NVDA"]
    # Sidebar FY badge: each company's latest reported FY (Option A basis), labelled per company.
    assert data[0]["ticker"] == "AAPL"
    assert data[0]["latest_fiscal_year"] == 2025
    assert data[0]["latest_fy_label"] == "FY2025 (ended 2025-09-27)"


def test_all_routes_registered() -> None:
    # FastAPI wraps included routers, so app.routes hides the APIRoutes; the OpenAPI paths are the
    # reliable registration surface.
    paths = create_app().openapi()["paths"]
    expected = {
        "/health",
        "/api/companies",
        "/api/companies/{ticker}/fundamentals",
        "/api/companies/{ticker}/prices",
        "/api/companies/{ticker}/valuation",
        "/api/companies/{ticker}/risk-diff",
        "/api/companies/{ticker}/insider",
        "/api/compare",
        "/api/meta/freshness",
    }
    assert expected <= set(paths)
