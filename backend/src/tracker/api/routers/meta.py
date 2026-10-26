"""Dataset freshness for the footer: stored maxima and row counts, never "today"."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.session import get_session
from tracker.services.meta import freshness

router = APIRouter(tags=["meta"])


@router.get("/meta/freshness", response_model=schemas.FreshnessOut, summary="Data freshness")
def meta_freshness(session: Session = Depends(get_session)) -> schemas.FreshnessOut:
    return schemas.FreshnessOut.model_validate(freshness(session))
