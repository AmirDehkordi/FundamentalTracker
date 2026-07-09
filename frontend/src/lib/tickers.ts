// Fixed per-ticker series colours (dashboard-design skill). Recharts takes colour props, not Tailwind
// classes, so the palette lives here as hex; it must stay in lockstep with `colors.ticker` in
// tailwind.config.ts and the skill.
// Reassigned so no ticker collides with a semantic (pos/neg/warn) or the amber accent — each hue is
// WCAG >= 5.9:1 on surface-1. Keep in lockstep with colors.ticker in tailwind.config.ts and the skill.
export const TICKER_COLORS: Record<string, string> = {
  NVDA: "#6E9BF0", // blue
  MSFT: "#2DB6A6", // teal
  AAPL: "#A78BFA", // violet
  GOOGL: "#CE7CA6", // muted rose — toned down to sit in one family with the others
  ETN: "#D68A5A", // muted terracotta — warm, harmonises with the amber accent, distinct from it
};

const FALLBACK = "#6E9BF0"; // NVDA blue, for any ticker outside the fixed universe

/** The series colour for a ticker (case-insensitive), falling back to a neutral series blue. */
export function tickerColor(ticker: string): string {
  return TICKER_COLORS[ticker.toUpperCase()] ?? FALLBACK;
}

// Display names replacing raw EDGAR caps ("MICROSOFT CORP") everywhere in the UI.
const DISPLAY_NAMES: Record<string, string> = {
  MSFT: "Microsoft",
  AAPL: "Apple",
  GOOGL: "Alphabet",
  NVDA: "NVIDIA",
  ETN: "Eaton",
};

/** Human display name for a ticker (case-insensitive); falls back to the raw name when unknown. */
export function displayName(
  ticker: string,
  fallback: string | null | undefined,
): string {
  return DISPLAY_NAMES[ticker.toUpperCase()] ?? fallback ?? ticker;
}

// Full legal entity names, correctly cased. SEC's own company_tickers.json/XBRL entityName are
// inconsistent ("MICROSOFT CORP", "EATON CORPORATION plc") so these are curated, not derived.
const FULL_LEGAL_NAMES: Record<string, string> = {
  MSFT: "Microsoft Corporation",
  AAPL: "Apple Inc.",
  GOOGL: "Alphabet Inc.",
  NVDA: "NVIDIA Corporation",
  ETN: "Eaton Corporation plc",
};

/** Full legal entity name for a ticker (case-insensitive); falls back to the raw name when unknown. */
export function fullLegalName(
  ticker: string,
  fallback: string | null | undefined,
): string {
  return FULL_LEGAL_NAMES[ticker.toUpperCase()] ?? fallback ?? ticker;
}
