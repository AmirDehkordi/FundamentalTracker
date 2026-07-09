/*
 * Wire types for the API. Two sources:
 *   A. Generated — re-exported from the openapi-typescript output (src/api/types.ts). Permanent.
 *   B. TEMPORARY hand mirrors of FROZEN contracts that openapi.json does not yet expose, because
 *      their routes are 501 stubs with no response_model. The source of truth is
 *      backend/src/tracker/api/schemas.py. Delete each mirror and move its type up into section A the
 *      moment the matching route registers a response_model and `npm run gen:types` re-emits it.
 *      Pydantic `date` fields serialize as ISO strings on the wire, so they are typed `string` here.
 */
import type { components } from "@/api/types";

// --- A. Generated (permanent) ------------------------------------------------------------------
export type CompanyOut = components["schemas"]["CompanyOut"];
export type ErrorOut = components["schemas"]["ErrorOut"];

// --- B. Temporary mirrors (delete per-route as the backend registers response models) -----------
export type MetricUnit = "USD" | "USD/shares" | "shares" | "percent" | "ratio";

// POST /api/ask — the grounded Q&A contract. Mirrors backend api/schemas.py (AskRequest / FinalAnswer
// et al.). The endpoint always returns HTTP 200: failures/refusals come back as `declined` answers.
export type CitationSource = "fundamental" | "filing" | "price" | "insider";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface AskRequest {
  question: string;
  history: Message[];
}

export interface Citation {
  source_type: CitationSource;
  ticker: string;
  fiscal_year?: number | null;
  item?: string | null; // "1A" | "7" for filing citations
  accession?: string | null;
  url?: string | null; // SEC Archives link
  detail: string; // human-readable, e.g. "Revenue $130.5B, FY2025 (ended 27 Sep 2025)"
}

export interface ToolTrace {
  tool: string;
  args: Record<string, unknown>;
  result_summary: string;
}

export interface FinalAnswer {
  answer_md: string;
  citations: Citation[];
  trace: ToolTrace[];
  declined: boolean;
  decline_reason?: string | null;
}

export interface MetricValue {
  value: number | null;
  unit: MetricUnit;
  reason?: string | null;
  accession?: string | null;
  superseded_value?: number | null;
  superseded_filed?: string | null;
}

export interface EpsSource {
  fiscal_year: number;
  period_end: string;
  accession: string;
  label: string;
}

export interface ValuationOut {
  ticker: string;
  cik: number;
  trailing_pe: MetricValue;
  trailing_ps: MetricValue;
  close: number;
  price_as_of: string;
  eps_source: EpsSource;
  basis_note?: string | null;
}

export interface FreshnessOut {
  max_price_date: string | null;
  max_filed_date: string | null;
  source_counts: Record<string, number>;
  company_count: number;
}

// Fundamentals matrix. `rows` is chronological ascending; the UI takes the last N. `metrics` carries
// raw concepts + fcf + margins + fcf_conversion; `yoy` carries raw-level YoY + operating_leverage.
// (Margins & fcf_conversion have no yoy cell; operating_leverage lives only in yoy — one ratio per row.)
export interface FundamentalsRow {
  fiscal_year: number;
  period_end: string;
  label: string;
  metrics: Record<string, MetricValue>;
  yoy: Record<string, MetricValue>;
}

export interface FundamentalsOut {
  ticker: string;
  cik: number;
  name: string;
  rows: FundamentalsRow[];
}

export interface PriceRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: string;
}

// A 10-K reference line on the price chart. `filed` is the x-position; `primary_doc_url` is the SEC link.
export interface FilingMarker {
  accession: string;
  form: string;
  fiscal_year: number;
  period_end: string;
  filed: string;
  primary_doc_url: string;
}

export interface PricesOut {
  ticker: string;
  cik: number;
  range: string;
  rows: PriceRow[];
  filings: FilingMarker[];
}

// One company's cell in a cross-company comparison, footnoted with ITS OWN fiscal year (alignment trap).
export interface CompareCell {
  ticker: string;
  cik: number;
  value: MetricValue;
  fiscal_year: number;
  period_end: string;
  label: string;
}

export interface CompareOut {
  metric: string;
  basis_note: string;
  rows: CompareCell[];
}

export interface FilingRef {
  fiscal_year: number;
  period_end: string;
  accession: string;
  primary_doc_url: string;
  label: string;
}

export interface RiskDiffCounts {
  added: number;
  removed: number;
  unchanged?: number | null;
}

// Item 1A year-over-year diff. Degraded state: `available === false` with a `note`, `prior` null.
export interface RiskDiffOut {
  ticker: string;
  cik: number;
  item: string;
  latest: FilingRef | null;
  prior: FilingRef | null;
  added: string[];
  removed: string[];
  counts: RiskDiffCounts;
  available: boolean;
  note?: string | null;
}

// Form 4 window. Counts include unpriced rows; notional sums use priced rows only, so a notional can be
// null (no priced transactions) even when a count is non-zero — that is an em dash, never $0.
export interface InsiderWindow {
  days: number;
  buy_count: number;
  sell_count: number;
  net_shares: number | null;
  net_notional: number | null;
  buy_notional?: number | null;
  sell_notional?: number | null;
}

export interface InsiderSummaryOut {
  ticker: string;
  cik: number;
  window_90d: InsiderWindow;
  window_365d: InsiderWindow;
  caveat: string;
  has_data: boolean;
}
