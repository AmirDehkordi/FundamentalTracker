"""FastAPI application factory.

Thin routers over services/ (api/routers/*.py); the frozen contracts live in schemas.py. This file
only assembles the app: CORS + router registration + (in the packaged container) the built frontend.
/health mounts at root; everything else under /api. Section order (companies, compare, meta) is the
/docs reading order.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tracker.api.routers import ask, companies, compare, health, meta

FRONTEND_ORIGIN = "http://localhost:5173"

# backend/src/tracker/api/app.py -> repo root is 4 parents up; kept relative (not absolute/env-
# configured) so the same code path resolves correctly both in local dev and in the Docker image,
# which preserves this same backend/... + frontend/dist layout under /app (see Dockerfile).
_FRONTEND_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"


def _app_version() -> str:
    try:
        return metadata.version("tracker")
    except metadata.PackageNotFoundError:
        return "0.0.0"  # package not installed (e.g. a bare test env)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA. No-op if `dist` doesn't exist (local `make run` without a frontend
    build) so dev workflows are unaffected. Registered after every API router, so /api and /health
    always win — the catch-all only ever sees paths those routers didn't already claim."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # Defensive: an unmatched /api/* or /health path is a real 404, never the SPA shell.
        if full_path == "health" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


def create_app() -> FastAPI:
    # Uvicorn only configures its own loggers; without a root handler the app's INFO lines
    # (llm_call token/latency accounting, ask latency) are silently dropped in the container.
    # basicConfig is a no-op when a root handler already exists, so tests/embedders are unaffected.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
    app.include_router(ask.router, prefix="/api")
    app.include_router(health.router)  # root; tagged "meta"
    if _FRONTEND_DIST.is_dir():
        _mount_frontend(app, _FRONTEND_DIST)
    return app
