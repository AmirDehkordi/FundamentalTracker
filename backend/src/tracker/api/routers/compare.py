"""Cross-company comparison of one metric on the latest-reported-FY-per-company basis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.concepts import CANONICAL_CONCEPTS
from tracker.db.session import get_session
from tracker.services.compare import compare as compare_service
from tracker.services.fundamentals import DERIVED_UNITS

router = APIRouter(tags=["compare"])

# Metrics the compare service can value: the 9 canonical concepts + the derived ratios. Derived from
# the frozen vocabulary so the whitelist can never drift from what the service supports.
SUPPORTED_METRICS: frozenset[str] = CANONICAL_CONCEPTS | frozenset(DERIVED_UNITS)


@router.get(
    "/compare",
    response_model=schemas.CompareOut,
    summary="Cross-company metric comparison",
    responses={422: {"model": schemas.ErrorOut, "description": "Unknown metric"}},
)
def compare_metric(
    metric: str = Query(
        ..., description="A canonical concept or a derived ratio (e.g. revenue_yoy)"
    ),
    session: Session = Depends(get_session),
) -> schemas.CompareOut:
    # The service returns all-null cells for an unsupported key rather than erroring, so the 422 is
    # enforced here — request validation, not business logic.
    if metric not in SUPPORTED_METRICS:
        raise HTTPException(status_code=422, detail=f"Unknown metric: {metric}")
    return schemas.CompareOut.model_validate(compare_service(session, metric))
