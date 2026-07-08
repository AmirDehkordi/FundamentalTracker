"""Shared router dependencies. Kept out of the frozen schemas and thin by design."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from tracker.db.session import get_session
from tracker.services import fundamentals


def require_company(
    ticker: str,
    session: Session = Depends(get_session),
) -> fundamentals.CompanyRef:
    """Resolve a path `{ticker}` to company identity, or 404.

    For the cik-keyed services (insider, risk-diff) and valuation, whose None conflates unknown
    ticker with missing data — those never signal an unknown company themselves.
    """
    company = fundamentals.get_company(session, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return company
