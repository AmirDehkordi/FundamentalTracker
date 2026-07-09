// Fixed per-ticker series colours (dashboard-design skill). Recharts takes colour props, not Tailwind
// classes, so the palette lives here as hex; it must stay in lockstep with `colors.ticker` in
// tailwind.config.ts and the skill.
export const TICKER_COLORS: Record<string, string> = {
  NVDA: "#6EA8FE",
  MSFT: "#34D399",
  AAPL: "#A78BFA",
  GOOGL: "#FBBF24",
  ETN: "#F87171",
};

const FALLBACK = "#6EA8FE"; // --accent, for any ticker outside the fixed universe

/** The series colour for a ticker (case-insensitive), falling back to the accent blue. */
export function tickerColor(ticker: string): string {
  return TICKER_COLORS[ticker.toUpperCase()] ?? FALLBACK;
}
