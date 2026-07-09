import type { Citation, CitationSource } from "@/api/contracts";

// source_type -> the label an analyst recognises. filing = 10-K narrative, fundamental = XBRL facts.
const CITATION_HEAD: Record<CitationSource, string> = {
  filing: "10-K",
  fundamental: "XBRL",
  price: "Price",
  insider: "Insider",
};

/**
 * A compact citation pill face, e.g. "NVDA · 10-K · FY2025 · Item 1A" or "AAPL · XBRL · FY2025 ·
 * accn …0010K". Ticker-first because comparative answers cite all five companies at once. The rich
 * `detail` string rides in the pill's title, not its face.
 */
export function citationLabel(c: Citation): string {
  const parts: string[] = [c.ticker, CITATION_HEAD[c.source_type]];
  if (c.fiscal_year != null) parts.push(`FY${c.fiscal_year}`);
  if (c.item) parts.push(`Item ${c.item}`);
  else if (
    c.accession &&
    (c.source_type === "fundamental" || c.source_type === "filing")
  )
    parts.push(`accn …${c.accession.slice(-6)}`);
  return parts.join(" · ");
}

const TOOL_LABEL: Record<string, string> = {
  get_fundamentals: "Fundamentals",
  compare_companies: "Compare companies",
  get_valuation: "Valuation",
  search_filings: "Search filings",
  diff_risk_factors: "Risk-factor diff",
  get_insider_activity: "Insider activity",
  list_universe: "Universe",
};

/** The recognisable name for a tool in the trace; unknown tools fall back to the raw name. */
export function friendlyTool(tool: string): string {
  return TOOL_LABEL[tool] ?? tool;
}

export interface ExampleQuestion {
  label: string;
  question: string;
}

// The brief's structured / comparative / cross-modal / filing-text examples (Q1 / Q2 / Q5 / Q4),
// sent verbatim; the short label is the chip face.
export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  {
    label: "NVDA revenue & net income, last 3 years",
    question:
      "What were NVDA's revenue and net income for the last three fiscal years?",
  },
  {
    label: "Highest gross margin last year",
    question:
      "Which of the five companies had the highest gross margin last year?",
  },
  {
    label: "MSFT revenue growth and why",
    question:
      "How did MSFT's revenue grow last year, and what did management attribute it to?",
  },
  {
    label: "What changed in NVDA's risk factors",
    question:
      "What new risk factors did NVDA add in its latest 10-K versus the prior year?",
  },
];
