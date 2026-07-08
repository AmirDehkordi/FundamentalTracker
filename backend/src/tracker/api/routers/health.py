"""Liveness probe at root (no /api prefix), reported under the meta tag."""

from __future__ import annotations

import sys

from fastapi import APIRouter, Request

from tracker.api import schemas

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=schemas.HealthOut, summary="Liveness + versions")
def health(request: Request) -> schemas.HealthOut:
    py = sys.version_info
    # app.version is set from the package version in create_app(); read it back to avoid importing
    # app.py here (routers must never import the factory).
    return schemas.HealthOut(
        status="ok",
        versions={"app": request.app.version, "python": f"{py.major}.{py.minor}.{py.micro}"},
    )
