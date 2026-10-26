"""Shared router dependencies. Kept out of the frozen schemas and thin by design."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from tracker.agent import llm
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


def optional_llm_client() -> Any | None:
    """The LLM client if configured, else None — for endpoints that can serve a cached result with
    no LLM at all, so an unconfigured LLM is not itself an error here. Tests override this to inject
    the fake client or None."""
    if not llm.llm_configured():
        return None
    return llm.get_llm_client()
