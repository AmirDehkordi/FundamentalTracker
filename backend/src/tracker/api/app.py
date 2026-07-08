"""FastAPI application factory.

Foundation scaffold: /health and /api/companies are live; every other data route is a clean 501
until P5 wires services. Routers are inline here on purpose for this chunk (scaffold = one legible
file). P5 extracts them into api/routers/*.py behind services/ WITHOUT touching the frozen
schemas.py — the contracts, not the wiring, are what is frozen.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import metadata

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import Company
from tracker.db.session import get_session

FRONTEND_ORIGIN = "http://localhost:5173"

# (path, human summary) for the not-yet-implemented data routes.
_STUB_ROUTES: list[tuple[str, str]] = [
    ("/companies/{ticker}/fundamentals", "Annual fundamentals matrix + YoY"),
    ("/companies/{ticker}/prices", "Daily prices + 10-K markers"),
    ("/companies/{ticker}/valuation", "Trailing P/E and P/S"),
    ("/companies/{ticker}/risk-diff", "Item 1A year-over-year diff"),
    ("/companies/{ticker}/insider", "Form 4 insider summary"),
    ("/compare", "Cross-company metric comparison"),
    ("/meta/freshness", "Data freshness"),
]


def _app_version() -> str:
    try:
        return metadata.version("tracker")
    except metadata.PackageNotFoundError:
        return "0.0.0"  # package not installed (e.g. a bare test env)


def _health_router() -> APIRouter:
    router = APIRouter(tags=["meta"])

    @router.get("/health", response_model=schemas.HealthOut, summary="Liveness + versions")
    def health() -> schemas.HealthOut:
        py = sys.version_info
        return schemas.HealthOut(
            status="ok",
            versions={"app": _app_version(), "python": f"{py.major}.{py.minor}.{py.micro}"},
        )

    return router


def _companies_router() -> APIRouter:
    router = APIRouter(tags=["companies"])

    @router.get(
        "/companies",
        response_model=list[schemas.CompanyOut],
        summary="List the tracked universe",
    )
    def list_companies(
        session: Session = Depends(get_session),
    ) -> list[schemas.CompanyOut]:
        # Tiny inline query for the scaffold. P5 moves this behind services.fundamentals and fills
        # the latest-FY fields; the CompanyOut contract already carries them, so no unfreeze.
        rows = session.scalars(select(Company).order_by(Company.ticker)).all()
        return [schemas.CompanyOut(cik=c.cik, ticker=c.ticker, name=c.name) for c in rows]

    return router


def _stub() -> Callable[[], None]:
    def handler() -> None:
        raise HTTPException(status_code=501, detail="Not implemented in the foundation chunk")

    return handler


def _stub_router() -> APIRouter:
    router = APIRouter(tags=["not yet implemented"])
    for path, summary in _STUB_ROUTES:
        router.add_api_route(
            path,
            _stub(),
            methods=["GET"],
            name=path,  # unique -> no OpenAPI operation_id collisions
            summary=summary,
            status_code=501,
            responses={501: {"model": schemas.ErrorOut, "description": "Not implemented yet"}},
        )
    return router


def create_app() -> FastAPI:
    app = FastAPI(title="Fundamentals Tracker API", version=_app_version())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(_health_router())
    app.include_router(_companies_router(), prefix="/api")
    app.include_router(_stub_router(), prefix="/api")
    return app
