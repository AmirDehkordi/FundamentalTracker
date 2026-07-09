"""The 7-tool registry: Pydantic args models + handlers that call the SAME services/ functions the
REST API uses (P8). This module imports NO openai — handlers stay unit-testable without the SDK, and
loop.py is the only agent module that drives the model.

Every handler returns a compact, JSON-safe dict that ALWAYS carries fiscal labels + provenance so
the model can cite. Handlers never raise for a data reason: an unknown ticker, an undefined metric
(None-with-reason), a degraded diff/insider window, or an empty search all come back as explicit
fields (`ok`, `error`, `available`, `has_data`, `count`, `reason`), and `call_tool` converts any
genuine handler bug into an `{"error": ...}` dict the model can read and recover from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from tracker.concepts import CANONICAL_CONCEPTS
from tracker.config import get_settings
from tracker.services import (
    compare as compare_svc,
)
from tracker.services import (
    fundamentals,
    insider,
    retrieval,
    riskdiff,
    valuation,
)
from tracker.services.metrics import Metric

logger = logging.getLogger("tracker.agent.tools")

# Metric keys a FyRow can actually carry (metrics + yoy). revenue_yoy is compare-only, so it is NOT
# here — filtering on it would silently drop rather than error.
_FUNDAMENTAL_KEYS: frozenset[str] = CANONICAL_CONCEPTS | {
    "fcf",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "fcf_conversion",
    "operating_leverage",
}

# The metrics compare can value: the 9 canonical concepts + the 7 derived ratios. Hand-spelled as a
# Literal for a self-documenting, mypy-checked enum; test_tools asserts it never drifts from the
# frozen service vocabulary (CANONICAL_CONCEPTS | DERIVED_UNITS).
CompareMetric = Literal[
    "revenue",
    "net_income",
    "eps_diluted",
    "gross_profit",
    "cost_of_revenue",
    "operating_income",
    "cfo",
    "capex",
    "shares_diluted",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "fcf_conversion",
    "operating_leverage",
    "revenue_yoy",
]


# ---------------------------------------------------------------------------
# shared serializers — uniform provenance + fiscal labels across every tool
# ---------------------------------------------------------------------------


def _metric_dict(m: Metric) -> dict[str, Any]:
    """A Metric -> smallest JSON-safe cell the model can cite. None values always carry `reason`
    (e.g. 'n.m. — negative EPS'); accession/restatement ride when present."""
    out: dict[str, Any] = {"value": m.value, "unit": m.unit}
    if m.reason is not None:
        out["reason"] = m.reason
    if m.accession is not None:
        out["accession"] = m.accession
    if m.superseded_value is not None:  # a restated prior value — keep it visible
        out["superseded_value"] = m.superseded_value
        out["superseded_filed"] = m.superseded_filed.isoformat() if m.superseded_filed else None
    return out


def _fiscal(label: str, fiscal_year: int, period_end: date) -> dict[str, Any]:
    """The fiscal-label triple every user-facing value must carry (CLAUDE.md non-negotiable)."""
    return {"label": label, "fiscal_year": fiscal_year, "period_end": period_end.isoformat()}


def _unknown_ticker(session: Session, ticker: str) -> dict[str, Any]:
    upper = ticker.upper()
    return {
        "ok": False,
        "error": "unknown_ticker",
        "ticker": upper,
        # Config universe is an annotation only — it lets the model phrase 'not tracked' vs 'no data
        # yet' precisely, but data resolution is the DB (get_company), never a config gate.
        "in_universe": upper in get_settings().universe_tickers,
        "detail": f"No tracked data for {upper}.",
    }


def _resolve(session: Session, ticker: str) -> fundamentals.CompanyRef | dict[str, Any]:
    """ticker -> CompanyRef, or a uniform unknown-ticker dict (never an exception). get_company
    upper-cases internally, so callers pass the raw ticker through."""
    company = fundamentals.get_company(session, ticker)
    if company is None:
        return _unknown_ticker(session, ticker)
    return company


# ---------------------------------------------------------------------------
# tool 1 — get_fundamentals (the tool does the concept/last_n filtering the service lacks)
# ---------------------------------------------------------------------------


class GetFundamentalsArgs(BaseModel):
    ticker: str = Field(description="Ticker symbol, e.g. AAPL. Case-insensitive.")
    concepts: list[str] | None = Field(
        default=None,
        description=(
            "Subset of metric keys to return. Allowed: revenue, cost_of_revenue, gross_profit, "
            "operating_income, net_income, eps_diluted, cfo, capex, shares_diluted, fcf, "
            "gross_margin, operating_margin, net_margin, fcf_margin, fcf_conversion, "
            "operating_leverage. Omit for all. Unknown names are ignored (see `ignored_concepts`)."
        ),
    )
    last_n_years: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Return only the most recent N fiscal years. Omit for all.",
    )


def get_fundamentals(session: Session, args: GetFundamentalsArgs) -> dict[str, Any]:
    company = _resolve(session, args.ticker)
    if isinstance(company, dict):
        return company
    result = fundamentals.get_fundamentals(session, args.ticker)
    if result is None:  # pragma: no cover - defensive: _resolve already caught unknown ticker
        return _unknown_ticker(session, args.ticker)

    rows = result.rows  # chronological ascending
    if args.last_n_years is not None:
        rows = rows[-args.last_n_years :]

    keep: set[str] | None = None
    ignored: list[str] = []
    if args.concepts:  # an explicit [] means 'no filter' (all metrics), same as omitting it
        keep = {c for c in args.concepts if c in _FUNDAMENTAL_KEYS}
        ignored = sorted(set(args.concepts) - keep)  # unknown names reported, never raised

    out_rows: list[dict[str, Any]] = []
    for r in rows:
        metrics = r.metrics if keep is None else {k: v for k, v in r.metrics.items() if k in keep}
        yoy = r.yoy if keep is None else {k: v for k, v in r.yoy.items() if k in keep}
        out_rows.append(
            {
                **_fiscal(r.label, r.fiscal_year, r.period_end),
                "metrics": {k: _metric_dict(v) for k, v in metrics.items()},
                "yoy": {k: _metric_dict(v) for k, v in yoy.items()},
            }
        )
    return {
        "ok": True,
        "ticker": result.ticker,
        "cik": result.cik,
        "name": result.name,
        "rows": out_rows,
        "ignored_concepts": ignored,
    }


# ---------------------------------------------------------------------------
# tool 2 — compare_companies (one required selector -> hard enum)
# ---------------------------------------------------------------------------


class CompareCompaniesArgs(BaseModel):
    metric: CompareMetric = Field(
        description="Metric to compare across the universe, each on its own latest reported FY."
    )


def compare_companies(session: Session, args: CompareCompaniesArgs) -> dict[str, Any]:
    res = compare_svc.compare(session, args.metric)  # never raises; unknown -> per-cell reason
    return {
        "ok": True,
        "metric": res.metric,
        "basis_note": res.basis_note,
        "rows": [
            {
                "ticker": row.ticker,
                "cik": row.cik,
                "value": _metric_dict(row.value),
                **_fiscal(row.label, row.fiscal_year, row.period_end),
            }
            for row in res.rows
        ],
    }


# ---------------------------------------------------------------------------
# tool 3 — get_valuation (whole-result None -> explicit ok:False)
# ---------------------------------------------------------------------------


class GetValuationArgs(BaseModel):
    ticker: str = Field(description="Ticker symbol, e.g. NVDA.")


def get_valuation(session: Session, args: GetValuationArgs) -> dict[str, Any]:
    company = _resolve(session, args.ticker)
    if isinstance(company, dict):
        return company
    res = valuation.get_valuation(session, args.ticker)
    if res is None:  # known ticker but no stored price / no reported FY
        return {
            "ok": False,
            "error": "no_valuation",
            "ticker": args.ticker.upper(),
            "detail": "No trailing multiples: missing stored price or reported fiscal year.",
        }
    e = res.eps_source
    return {
        "ok": True,
        "ticker": res.ticker,
        "cik": res.cik,
        "trailing_pe": _metric_dict(
            res.trailing_pe
        ),  # value None + 'n.m. — negative EPS' when n.m.
        "trailing_ps": _metric_dict(res.trailing_ps),
        "close": res.close,
        "price_as_of": res.price_as_of.isoformat(),
        "eps_source": {
            "accession": e.accession,
            **_fiscal(e.label, e.fiscal_year, e.period_end),
        },
        "basis_note": res.basis_note,
    }


# ---------------------------------------------------------------------------
# tool 4 — search_filings (resolve ticker -> CIK-keyed retrieval)
# ---------------------------------------------------------------------------


class SearchFilingsArgs(BaseModel):
    ticker: str = Field(description="Ticker whose 10-K filings to search.")
    query: str = Field(min_length=1, description="Free-text query (websearch semantics).")
    item: Literal["1A", "7"] | None = Field(
        default=None,
        description="Restrict to a 10-K item: 1A (risk factors) or 7 (MD&A). Omit for all.",
    )
    fiscal_year: int | None = Field(
        default=None,
        ge=1990,
        le=2100,
        description="Restrict to a single fiscal year. Omit for all.",
    )


def search_filings(session: Session, args: SearchFilingsArgs) -> dict[str, Any]:
    # This is the one tool that streams untrusted filing text into the model context. The snippets
    # are curated SEC 10-K prose (low injection risk) and the system prompt bounds behaviour; we
    # accept that risk rather than framing/escaping each snippet in this prototype.
    company = _resolve(session, args.ticker)
    if isinstance(company, dict):
        return company
    hits = retrieval.search_chunks(
        session, company.cik, args.query, item=args.item, fiscal_year=args.fiscal_year, limit=8
    )
    return {
        "ok": True,
        "ticker": company.ticker,
        "cik": company.cik,
        "query": args.query,
        "count": len(hits),  # 0 is a first-class 'no matches', not an error
        "hits": [
            {
                "accession": h.accession,
                "item": h.item,
                "fiscal_year": h.fiscal_year,
                "chunk_index": h.chunk_index,
                "snippet": h.snippet,
                "url": h.url,
            }
            for h in hits
        ],
    }


# ---------------------------------------------------------------------------
# tool 5 — diff_risk_factors (degraded -> available:False + note)
# ---------------------------------------------------------------------------


class DiffRiskFactorsArgs(BaseModel):
    ticker: str = Field(description="Ticker whose Item 1A risk factors to diff year over year.")


def _filing_ref(ref: riskdiff.FilingRefData | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    return {
        "accession": ref.accession,
        "url": ref.primary_doc_url,
        **_fiscal(ref.label, ref.fiscal_year, ref.period_end),
    }


def diff_risk_factors(session: Session, args: DiffRiskFactorsArgs) -> dict[str, Any]:
    company = _resolve(session, args.ticker)
    if isinstance(company, dict):
        return company
    res = riskdiff.diff_risk_factors(session, company.cik, item="1A")  # never raises
    return {
        "ok": True,
        "ticker": res.ticker,
        "cik": res.cik,
        "item": res.item,
        "available": res.available,  # degraded state as explicit fields, not an error
        "note": res.note,
        "latest": _filing_ref(res.latest),
        "prior": _filing_ref(res.prior),
        "added": res.added,
        "removed": res.removed,
        "counts": {
            "added": res.counts.added,
            "removed": res.counts.removed,
            "unchanged": res.counts.unchanged,
        },
    }


# ---------------------------------------------------------------------------
# tool 6 — get_insider_activity (window-based; has_data flag, standing 10b5-1 caveat)
# ---------------------------------------------------------------------------


class GetInsiderActivityArgs(BaseModel):
    ticker: str = Field(description="Ticker whose Form 4 insider activity to summarize.")


def _window(w: insider.InsiderWindowData) -> dict[str, Any]:
    return {
        "days": w.days,
        "buy_count": w.buy_count,
        "sell_count": w.sell_count,
        "net_shares": w.net_shares,
        "net_notional": w.net_notional,
        "buy_notional": w.buy_notional,
        "sell_notional": w.sell_notional,
    }


def get_insider_activity(session: Session, args: GetInsiderActivityArgs) -> dict[str, Any]:
    company = _resolve(session, args.ticker)
    if isinstance(company, dict):
        return company
    # Known limitation: the service anchors its windows to the latest Form 4 filed date but does not
    # expose that anchor, so the payload carries no explicit "as of" — the standing 10b5-1 caveat is
    # the provenance line. Surfacing the anchor is a services/ change, out of scope for this lane.
    res = insider.summary(session, company.cik)
    return {
        "ok": True,
        "ticker": res.ticker,
        "cik": res.cik,
        "has_data": res.has_data,  # window-based: the standing caveat is the provenance line
        "caveat": res.caveat,
        "window_90d": _window(res.window_90d),
        "window_365d": _window(res.window_365d),
    }


# ---------------------------------------------------------------------------
# tool 7 — list_universe (no args)
# ---------------------------------------------------------------------------


class ListUniverseArgs(BaseModel):
    """No arguments — present so the schema generator and dispatch treat every tool uniformly."""


def list_universe(session: Session, _args: ListUniverseArgs) -> dict[str, Any]:
    return {
        "ok": True,
        "companies": [
            {
                "cik": c.cik,
                "ticker": c.ticker,
                "name": c.name,
                "latest_fiscal_year": c.latest_fiscal_year,
                "latest_period_end": (
                    c.latest_period_end.isoformat() if c.latest_period_end else None
                ),
                "latest_fy_label": c.latest_fy_label,
            }
            for c in fundamentals.list_companies(session)
        ],
    }


# ---------------------------------------------------------------------------
# registry, schema generation, dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Session, Any], dict[str, Any]]


def _spec[M: BaseModel](
    name: str,
    description: str,
    model: type[M],
    handler: Callable[[Session, M], dict[str, Any]],
) -> ToolSpec:
    """Typed registration: mypy checks `handler` against its concrete `model` here; storage erases
    the arg type to Any so every spec shares one uniform shape."""
    return ToolSpec(name=name, description=description, args_model=model, handler=handler)


TOOLS: dict[str, ToolSpec] = {
    s.name: s
    for s in [
        _spec(
            "get_fundamentals",
            "Annual fundamentals matrix + YoY for one company, optionally filtered by concept and "
            "the last N fiscal years.",
            GetFundamentalsArgs,
            get_fundamentals,
        ),
        _spec(
            "compare_companies",
            "One metric across the whole universe, each on its latest reported fiscal year.",
            CompareCompaniesArgs,
            compare_companies,
        ),
        _spec(
            "get_valuation",
            "Trailing P/E and P/S for one company with EPS and price provenance.",
            GetValuationArgs,
            get_valuation,
        ),
        _spec(
            "search_filings",
            "Full-text search a company's 10-K chunks; returns cited snippets with SEC URLs.",
            SearchFilingsArgs,
            search_filings,
        ),
        _spec(
            "diff_risk_factors",
            "Deterministic year-over-year diff of a company's Item 1A risk factors.",
            DiffRiskFactorsArgs,
            diff_risk_factors,
        ),
        _spec(
            "get_insider_activity",
            "Form 4 insider buy/sell summary over trailing 90-day and 365-day windows.",
            GetInsiderActivityArgs,
            get_insider_activity,
        ),
        _spec(
            "list_universe",
            "List the tracked companies with their latest reported fiscal year.",
            ListUniverseArgs,
            list_universe,
        ),
    ]
}


def openai_tools_schema() -> list[dict[str, Any]]:
    """The single source of the OpenAI `tools` array — generated from the Pydantic args models,
    never hand-written. Args models are flat, so `model_json_schema()` inlines with no `$defs`."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            },
        }
        for spec in TOOLS.values()
    ]


def call_tool(session: Session, name: str, raw_args_json: str) -> dict[str, Any]:
    """Dispatch used by loop.py. Every failure mode returns a dict — the loop never sees an
    exception. `""` normalizes to `{}` for the no-arg tools."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": "unknown_tool", "detail": name}
    try:
        args = spec.args_model.model_validate_json(raw_args_json or "{}")
    except ValidationError as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "detail": exc.errors(include_url=False, include_context=False),
        }
    try:
        return spec.handler(session, args)
    except Exception as exc:  # not silent: log + surface, so one tool bug can't crash the loop
        logger.exception("tool %s failed", name)
        return {"ok": False, "error": "tool_failed", "detail": str(exc)}


def summarize(name: str, result: dict[str, Any]) -> str:
    """A short (<=120 char after loop truncation) human line for the tool trace."""
    if result.get("ok") is False or "error" in result:
        return f"{name} → {result.get('error', 'error')}: {result.get('detail', '')}"
    if name == "get_fundamentals":
        return f"{result['ticker']}: {len(result['rows'])} FY rows"
    if name == "compare_companies":
        return f"{result['metric']}: {len(result['rows'])} companies"
    if name == "get_valuation":
        return (
            f"{result['ticker']} P/E={result['trailing_pe'].get('value')} "
            f"P/S={result['trailing_ps'].get('value')}"
        )
    if name == "search_filings":
        return f"{result['ticker']} '{result['query']}': {result['count']} hits"
    if name == "diff_risk_factors":
        c = result["counts"]
        return (
            f"{result['ticker']} 1A +{c['added']}/-{c['removed']} available={result['available']}"
        )
    if name == "get_insider_activity":
        return f"{result['ticker']} insider has_data={result['has_data']}"
    if name == "list_universe":
        return f"{len(result['companies'])} companies"
    return f"{name} ok"
