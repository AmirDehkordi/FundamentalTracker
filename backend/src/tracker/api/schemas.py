"""Frozen API response/request contracts (Pydantic v2).

These are the wire boundary for both the REST API and the agent's structured output. Do NOT change a
field without an explicit unfreeze (CLAUDE.md: "contracts live in api/schemas.py and are frozen").

Money and metric values cross the wire as `float`, never `Decimal`: the DB and services keep
NUMERIC/Decimal, but JSON floats keep the generated TS types numeric for Recharts/formatting. These
floats are for display only — the DB is the source of truth for any exact arithmetic. Magnitudes
here (revenue ~1e12, shares ~1e10) sit inside float's exact-integer range (2^53 ≈ 9e15).

`metrics`/`yoy` dicts are keyed by `str`, not a concept Literal, on purpose: adding a derived-ratio
key (e.g. `net_margin`) later needs no unfreeze. `FinalAnswer` doubles as the LLM structured-output
target (P8 builds any strict json_schema variant from it without weakening this contract).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# shared base
# ---------------------------------------------------------------------------


class APIModel(BaseModel):
    # extra="forbid": reject drift / hallucinated fields (esp. on requests and the LLM answer).
    # from_attributes: build responses straight from ORM rows via model_validate(orm_obj).
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------

MetricUnit = Literal["USD", "USD/shares", "shares", "percent", "ratio", "percentage_points"]
CitationSource = Literal["fundamental", "filing", "price", "insider"]


class MetricValue(APIModel):
    """One metric cell: a value, or an explicit None-with-reason.

    Formatting is driven entirely by `unit` so the frontend never guesses:
      USD               -> adaptive '$130.5B' / '$964M'
      USD/shares        -> '$1.19'
      shares            -> count
      percent           -> value*100, 1dp, '%'   (margin LEVELS + level YoY: 0.114 -> '+11.4%')
      ratio             -> 'x'-suffixed          (P/E, P/S, FCF conversion, reinvestment ratio)
      percentage_points -> value*100, 1dp, 'pp'  (margin YoY: 0.02 -> '+2.0pp', NOT a % change)

    `reason` is populated iff `value is None`; the UI renders 'n.m. — <reason>'. `superseded_*`
    surface a restatement (latest-filed-wins kept the prior value visible) so the UI can tooltip
    'restated — originally …'.
    """

    value: float | None
    unit: MetricUnit
    reason: str | None = None
    accession: str | None = None
    superseded_value: float | None = None
    superseded_filed: date | None = None


# ---------------------------------------------------------------------------
# companies
# ---------------------------------------------------------------------------


class CompanyOut(APIModel):
    """Identity for the sidebar. Latest-FY fields let the FY badge render from this one call; they
    are None until ingestion (P2) has run."""

    cik: int
    ticker: str
    name: str
    latest_fiscal_year: int | None = None
    latest_period_end: date | None = None
    latest_fy_label: str | None = None  # "FY2025 (ended 2025-09-27)"
    # latest close x latest-reported-FY diluted shares (same approximation as trailing P/S); None
    # when either input is missing. Sort-only field — no MetricValue reason needed.
    market_cap: float | None = None


# ---------------------------------------------------------------------------
# fundamentals
# ---------------------------------------------------------------------------


class FundamentalsRow(APIModel):
    """One fiscal year. `metrics` = raw canonical concepts, `fcf`, and the derived margins
    (gross_margin, operating_margin, net_margin, fcf_margin, fcf_conversion, capex_intensity,
    reinvestment_ratio) in display order. `yoy` carries this-FY-vs-prior-FY for the raw levels +
    `fcf` (unit 'percent', % change) and the margins + fcf_conversion + capex_intensity +
    reinvestment_ratio (unit 'percentage_points', a pp delta). Each value is a MetricValue, so a
    None YoY carries its reason ('sign change / non-positive base')."""

    fiscal_year: int
    period_end: date
    label: str  # "FY2025 (ended 2025-09-27)"
    metrics: dict[str, MetricValue]
    yoy: dict[str, MetricValue]


class FundamentalsOut(APIModel):
    ticker: str
    cik: int
    name: str
    rows: list[FundamentalsRow]  # chronological ascending; UI takes the last N


# ---------------------------------------------------------------------------
# prices (+ embedded 10-K filing markers for the chart reference lines)
# ---------------------------------------------------------------------------


class PriceRow(APIModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str  # "yfinance" | "stooq" — provenance kept honest per row


class FilingMarker(APIModel):
    """A 10-K reference line on the price chart (§9). Embedded in the price view rather than a
    separate /filings endpoint — the markers are intrinsic to it, so none is needed."""

    accession: str
    form: str  # "10-K"
    fiscal_year: int
    period_end: date
    filed: date  # x-position of the reference line
    primary_doc_url: str  # SEC Archives link-out


class PricesOut(APIModel):
    ticker: str
    cik: int
    range: str  # echoes the requested range: "1m" | "6m" | "1y" | "2y"
    rows: list[PriceRow]
    filings: list[FilingMarker]


# ---------------------------------------------------------------------------
# valuation
# ---------------------------------------------------------------------------


class EpsSource(APIModel):
    fiscal_year: int
    period_end: date
    accession: str
    label: str  # "FY2025 (ended 2025-09-27)"


class ValuationOut(APIModel):
    """Both 'as of' bases are always explicit (§4): the EPS FY and the price date. P/E and P/S are
    MetricValue so 'n.m. — negative EPS' rides with them."""

    ticker: str
    cik: int
    trailing_pe: MetricValue  # unit "ratio"
    trailing_ps: MetricValue  # unit "ratio"
    close: float  # the close used (max stored trading date)
    price_as_of: date  # labelled, never implied "today"
    eps_source: EpsSource
    basis_note: str | None = None  # e.g. P/S diluted-WAD-shares caveat (decision log #11)


# ---------------------------------------------------------------------------
# compare (cross-company; each cell footnoted with its OWN FY label)
# ---------------------------------------------------------------------------


class CompareCell(APIModel):
    ticker: str
    cik: int
    value: MetricValue  # a company may be n.m. (e.g. op. leverage on a revenue fall)
    fiscal_year: int
    period_end: date
    label: str  # the alignment trap surfaced — each company's own FY


class CompareOut(APIModel):
    metric: str  # echoes the requested metric key
    basis_note: str  # "Basis: latest reported fiscal year per company."
    rows: list[CompareCell]


# ---------------------------------------------------------------------------
# risk-factor diff
# ---------------------------------------------------------------------------


class FilingRef(APIModel):
    fiscal_year: int
    period_end: date
    accession: str
    primary_doc_url: str
    label: str


class RiskDiffCounts(APIModel):
    added: int
    removed: int
    unchanged: int | None = None  # optional; card shows added/removed only


class RiskDiffOut(APIModel):
    """Deterministic Item 1A diff between the two stored FYs. `available=False` with a `note` covers
    the extraction-failed degraded state (§13)."""

    ticker: str
    cik: int
    item: str  # "1A"
    # Nullable for the degraded state: with <2 filed years there is no pair to reference (§13). The
    # required-FilingRef form could not represent the very state this schema's docstring documents.
    latest: FilingRef | None
    prior: FilingRef | None
    added: list[str]  # paragraph excerpts
    removed: list[str]
    counts: RiskDiffCounts
    available: bool = True
    note: str | None = None


class RiskThemeItem(APIModel):
    """One clustered risk theme grouping several diff excerpts. Grounded ONLY in the deterministic
    diff text."""

    title: str  # <= 6 words
    summary: str  # <= 30 words
    paragraph_count: int  # how many source excerpts this theme groups


class RiskDiffThemesOut(APIModel):
    """Top-3 thematic clusters of newly added/heightened and top-3 of removed/reduced risks
    (§8/§14). The diff itself stays deterministic; only the clustering/summarisation is the model's.
    `available=False` mirrors RiskDiffOut's degraded state; a diff with two filed years but no net
    changes is `available=True` with both theme lists empty."""

    ticker: str
    cik: int
    item: str  # "1A"
    latest: FilingRef | None
    prior: FilingRef | None
    added_themes: list[RiskThemeItem]  # top 3
    removed_themes: list[RiskThemeItem]  # top 3
    available: bool = True
    note: str | None = None


# ---------------------------------------------------------------------------
# insider (Form 4 summary)
# ---------------------------------------------------------------------------


class InsiderWindow(APIModel):
    days: int  # 90 | 365
    buy_count: int
    sell_count: int
    net_shares: float | None  # buys - sells; None if indeterminate
    net_notional: float | None  # priced rows only; None if none priced
    buy_notional: float | None = None
    sell_notional: float | None = None


class InsiderSummaryOut(APIModel):
    ticker: str
    cik: int
    window_90d: InsiderWindow
    window_365d: InsiderWindow
    caveat: str  # standing 10b5-1 caveat line (signal not oversold)
    has_data: bool  # False -> deliberate empty state
    history_capped: bool  # True -> ingestion's per-company filing cap may hide older activity


# ---------------------------------------------------------------------------
# agent Q&A
# ---------------------------------------------------------------------------


class Message(APIModel):
    # role is intentionally NOT 'system' — clients never inject a system turn.
    role: Literal["user", "assistant"]
    content: str


class AskRequest(APIModel):
    question: str = Field(min_length=1)
    history: list[Message] = Field(default_factory=list)


class Citation(APIModel):
    """`fiscal_year` is optional: price citations ('as of 2026-07-03') have no FY; fundamental and
    filing citations always carry it."""

    source_type: CitationSource
    ticker: str
    fiscal_year: int | None = None
    item: str | None = None  # "1A" | "7" for filing citations
    accession: str | None = None
    url: str | None = None  # SEC Archives link
    detail: str  # human-readable, e.g. "Revenue $130.5B, FY2025 (ended 27 Sep 2025)"


class ToolTrace(APIModel):
    tool: str
    args: dict[str, Any]
    result_summary: str  # <= 120 chars (P8)


AnswerKind = Literal["answer", "clarification", "decline", "error"]


class FinalAnswer(APIModel):
    """The /api/ask response AND the schema bound to the LLM's structured output (P8 transport
    ladder). Kept flat for proxy compatibility; extra='forbid' catches hallucinated fields and
    triggers the schema retry.

    `kind` splits the four outcomes the UI styles differently: a real `answer`; a `clarification`
    (the agent asks ONE conversational question back — not a refusal); a `decline` (out of scope /
    advice / forward-looking); an `error` (loop/endpoint failure). `declined` stays, and is derived
    (`kind in {decline, error}`) for backward compatibility. `suggested_followups` are 1-3 natural-
    language prompts the UI renders as chips — on a clarification, answerable rephrasings; on a
    decline, in-scope alternatives."""

    answer_md: str
    citations: list[Citation] = Field(default_factory=list)
    trace: list[ToolTrace] = Field(default_factory=list)
    kind: AnswerKind = "answer"
    suggested_followups: list[str] = Field(default_factory=list)
    declined: bool = False
    decline_reason: str | None = None


# ---------------------------------------------------------------------------
# meta / shared
# ---------------------------------------------------------------------------


class HealthOut(APIModel):
    status: Literal["ok"]
    versions: dict[str, str]  # open map: {"app": "0.1.0", "python": "3.12.x", ...}


class FreshnessOut(APIModel):
    """Freshness footer (§9/§10). Dates are None before ingestion; never 'today'."""

    max_price_date: date | None
    max_filed_date: date | None
    source_counts: dict[str, int]  # {"yfinance": 2480, "stooq": 20, "fundamentals": 312}
    company_count: int


class ErrorOut(APIModel):
    detail: str
