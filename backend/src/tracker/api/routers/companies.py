"""Company-scoped routes: the universe list plus the five per-ticker panels.

Thin wiring only — each handler resolves the ticker, calls one service, and maps the frozen
dataclass result onto the frozen schema via model_validate. Unknown ticker -> 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.api.deps import require_company
from tracker.db.session import get_session
from tracker.services import fundamentals, insider, prices, riskdiff, valuation

router = APIRouter(tags=["companies"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": schemas.ErrorOut, "description": "Unknown ticker"}
}


@router.get(
    "/companies",
    response_model=list[schemas.CompanyOut],
    summary="List the tracked universe",
)
def list_companies(session: Session = Depends(get_session)) -> list[schemas.CompanyOut]:
    return [schemas.CompanyOut.model_validate(c) for c in fundamentals.list_companies(session)]


@router.get(
    "/companies/{ticker}/fundamentals",
    response_model=schemas.FundamentalsOut,
    summary="Annual fundamentals matrix + YoY",
    responses=_NOT_FOUND,
)
def company_fundamentals(
    ticker: str, session: Session = Depends(get_session)
) -> schemas.FundamentalsOut:
    result = fundamentals.get_fundamentals(session, ticker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return schemas.FundamentalsOut.model_validate(result)


@router.get(
    "/companies/{ticker}/prices",
    response_model=schemas.PricesOut,
    summary="Daily prices + 10-K markers",
    responses=_NOT_FOUND,
)
def company_prices(
    ticker: str,
    range_: str = Query("2y", alias="range", description="1m | 6m | 1y | 2y (unknown -> 2y)"),
    session: Session = Depends(get_session),
) -> schemas.PricesOut:
    result = prices.get_prices(session, ticker, range_)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return schemas.PricesOut.model_validate(result)


@router.get(
    "/companies/{ticker}/valuation",
    response_model=schemas.ValuationOut,
    summary="Trailing P/E and P/S",
    responses=_NOT_FOUND,
)
def company_valuation(
    company: fundamentals.CompanyRef = Depends(require_company),
    session: Session = Depends(get_session),
) -> schemas.ValuationOut:
    result = valuation.trailing_multiples(session, company.cik)
    if result is None:
        # Known ticker, but no stored price or reported FY — ValuationOut.close is required, so
        # there is no valid degraded payload to return.
        raise HTTPException(
            status_code=404,
            detail=f"No valuation data for {company.ticker}: no stored price or reported FY",
        )
    return schemas.ValuationOut.model_validate(result)


@router.get(
    "/companies/{ticker}/risk-diff",
    response_model=schemas.RiskDiffOut,
    summary="Item 1A year-over-year diff",
    responses=_NOT_FOUND,
)
def company_risk_diff(
    company: fundamentals.CompanyRef = Depends(require_company),
    session: Session = Depends(get_session),
) -> schemas.RiskDiffOut:
    return schemas.RiskDiffOut.model_validate(
        riskdiff.diff_risk_factors(session, company.cik, item="1A")
    )


@router.get(
    "/companies/{ticker}/insider",
    response_model=schemas.InsiderSummaryOut,
    summary="Form 4 insider summary",
    responses=_NOT_FOUND,
)
def company_insider(
    company: fundamentals.CompanyRef = Depends(require_company),
    session: Session = Depends(get_session),
) -> schemas.InsiderSummaryOut:
    return schemas.InsiderSummaryOut.model_validate(insider.summary(session, company.cik))
