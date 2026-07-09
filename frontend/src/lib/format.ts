import type { MetricUnit, MetricValue } from "@/api/contracts";

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

/** KPI/panel fiscal sublabel from a row: "FY2025 · ended 27 Sep 2025". */
export function formatFySublabel(
  fiscalYear: number,
  periodEnd: string,
): string {
  return `FY${fiscalYear} · ended ${formatDayMonthYear(periodEnd)}`;
}

/** Ratio to 1 dp with an 'x' suffix: 54.31 -> "54.3x"; null -> em dash. */
export function formatRatio(v: number | null | undefined): string {
  return v == null ? EM_DASH : `${v.toFixed(1)}x`;
}

/** Freshness line: "2026-07-03" -> "Prices as of 3 Jul 2026"; null -> "Prices as of —". */
export function formatPricesAsOf(iso: string | null | undefined): string {
  return `Prices as of ${formatDayMonthYear(iso)}`;
}

function isNum(v: number | null | undefined): v is number {
  return v != null && Number.isFinite(v);
}

/** Adaptive USD magnitude: 1.305e11 -> "$130.5B", 9.64e8 -> "$964M", sign-aware; null -> em dash. */
export function formatUsd(v: number | null | undefined): string {
  if (!isNum(v)) return EM_DASH;
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(1)}T`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6)
    return `${sign}$${Math.round(a / 1e6).toLocaleString("en-US")}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
  return `${sign}$${a.toFixed(2)}`;
}

const usd2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Per-share / price money to 2 dp: 1.19 -> "$1.19". NOT adaptive — cents matter here. */
export function formatPerShare(v: number | null | undefined): string {
  return isNum(v) ? usd2.format(v) : EM_DASH;
}

/** Alias for share prices in the chart tooltip — same 2-dp rule; cents matter. */
export const formatPrice = formatPerShare;

/** Adaptive share count: 24.5e9 -> "24.5B", sign-aware; null -> em dash. No currency symbol. */
export function formatShares(v: number | null | undefined): string {
  if (!isNum(v)) return EM_DASH;
  const sign = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(1)}K`;
  return `${sign}${Math.round(a).toLocaleString("en-US")}`;
}

/** Unsigned percent from a fraction: 0.624 -> "62.4%" (a negative fraction still shows its minus). */
export function formatPercent(v: number | null | undefined): string {
  return isNum(v) ? `${(v * 100).toFixed(1)}%` : EM_DASH;
}

/** Signed percent for deltas/YoY: 0.114 -> "+11.4%", -0.032 -> "-3.2%"; null -> em dash. */
export function formatSignedPercent(v: number | null | undefined): string {
  if (!isNum(v)) return EM_DASH;
  const pct = v * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

/** Relative change (curr-prior)/prior as a fraction; null when prior is missing/<=0 or curr missing. */
export function relativeChange(
  curr: number | null | undefined,
  prior: number | null | undefined,
): number | null {
  if (!isNum(curr) || !isNum(prior) || prior <= 0) return null;
  return (curr - prior) / prior;
}

function formatByUnit(value: number, unit: MetricUnit): string {
  switch (unit) {
    case "USD":
      return formatUsd(value);
    case "USD/shares":
      return formatPerShare(value);
    case "shares":
      return formatShares(value);
    // NOTE: percent is UNSIGNED here — it covers both margins (unsigned) and YoY (signed). Only the
    // caller knows a cell came from the `yoy` dict, so YoY/delta callers apply formatSignedPercent
    // themselves. Do NOT "fix" this to always sign percents.
    case "percent":
      return formatPercent(value);
    case "ratio":
      return formatRatio(value);
  }
}

/** A MetricValue's display text by unit; a null value renders as an em dash (reason lives in the tooltip). */
export function formatMetric(m: MetricValue): string {
  return isNum(m.value) ? formatByUnit(m.value, m.unit) : EM_DASH;
}

export interface MetricDisplay {
  /** What to render in the cell. */
  text: string;
  /** Tooltip copy, or null when the value is plain and needs none. */
  tooltip: string | null;
  /** value present but a prior filing reported a different number. */
  restated: boolean;
  /** value is null (n.m. with a reason, or a bare data gap). */
  missing: boolean;
}

/**
 * Resolve a MetricValue to display text + tooltip, distinguishing four cases:
 *  - present, clean            -> value, no tooltip
 *  - present, restated         -> value, "restated — originally … (filed …)"
 *  - null with a reason        -> "n.m.", tooltip = reason
 *  - null, no reason (bare gap)-> em dash, generic tooltip (override via `missingFallback`)
 */
export function describeMetric(
  m: MetricValue,
  missingFallback = "Not reported for this fiscal year.",
): MetricDisplay {
  if (isNum(m.value)) {
    if (m.superseded_value != null) {
      const original = formatByUnit(m.superseded_value, m.unit);
      const filed = m.superseded_filed
        ? ` (filed ${formatDayMonthYear(m.superseded_filed)})`
        : "";
      return {
        text: formatMetric(m),
        tooltip: `Restated — originally ${original}${filed}.`,
        restated: true,
        missing: false,
      };
    }
    return {
      text: formatMetric(m),
      tooltip: null,
      restated: false,
      missing: false,
    };
  }
  if (m.reason) {
    return { text: "n.m.", tooltip: m.reason, restated: false, missing: true };
  }
  return {
    text: EM_DASH,
    tooltip: missingFallback,
    restated: false,
    missing: true,
  };
}
