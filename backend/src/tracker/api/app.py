"""FastAPI application factory.

Thin routers over services/ (api/routers/*.py); the frozen contracts live in schemas.py. This file
only assembles the app: CORS + router registration. /health mounts at root; everything else under
/api. Section order (companies, compare, meta) is the /docs reading order.
"""

from __future__ import annotations

from importlib import metadata

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tracker.api.routers import companies, compare, health, meta

FRONTEND_ORIGIN = "http://localhost:5173"


def _app_version() -> str:
    try:
        return metadata.version("tracker")
    except metadata.PackageNotFoundError:
        return "0.0.0"  # package not installed (e.g. a bare test env)


def create_app() -> FastAPI:
    app = FastAPI(title="Fundamentals Tracker API", version=_app_version())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(companies.router, prefix="/api")
    app.include_router(compare.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    app.include_router(health.router)  # root; tagged "meta"
    return app
