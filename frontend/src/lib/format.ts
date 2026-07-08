export const EM_DASH = "—";

/** A value, or an em dash when it is null/empty. */
export function orDash(s: string | null | undefined): string {
  return s == null || s === "" ? EM_DASH : s;
}

// UTC-pinned: an ISO date like "2025-09-27" is UTC midnight, so formatting in a local zone west of
// GMT would render "26 Sep". Forcing timeZone:"UTC" keeps the fiscal date honest everywhere.
const dayMonthYear = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "2025-09-27" -> "27 Sep 2025"; null/invalid -> em dash. */
export function formatDayMonthYear(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return dayMonthYear.format(d);
}

/** Top-bar chip: "Latest: FY2025 · ended 27 Sep 2025"; no reported FY -> em dash. */
export function formatFyChip(c: {
  latest_fiscal_year?: number | null;
  latest_period_end?: string | null;
}): string {
  if (c.latest_fiscal_year == null) return EM_DASH;
  const end = c.latest_period_end
    ? ` · ended ${formatDayMonthYear(c.latest_period_end)}`
    : "";
  return `Latest: FY${c.latest_fiscal_year}${end}`;
}

/** Compact sidebar badge: "FY2025"; no reported FY -> em dash. */
export function formatFyBadge(
  latestFiscalYear: number | null | undefined,
): string {
  return latestFiscalYear == null ? EM_DASH : `FY${latestFiscalYear}`;
}

/** Ratio to 1 dp with an 'x' suffix: 54.31 -> "54.3x"; null -> em dash. */
export function formatRatio(v: number | null | undefined): string {
  return v == null ? EM_DASH : `${v.toFixed(1)}x`;
}

/** Freshness line: "2026-07-03" -> "Prices as of 3 Jul 2026"; null -> "Prices as of —". */
export function formatPricesAsOf(iso: string | null | undefined): string {
  return `Prices as of ${formatDayMonthYear(iso)}`;
}
