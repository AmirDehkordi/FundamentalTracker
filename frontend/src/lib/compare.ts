// Client-side derivations for the Compare tab's second chart (per-company year-over-year change) and
// the shared sort order applied to both charts + the table.
import type { CompareCell, FundamentalsOut } from "@/api/contracts";
import {
  formatPp,
  formatSignedPercent,
  pointChange,
  relativeChange,
} from "@/lib/format";
import { MARGIN_KEYS, metricAt } from "@/lib/metrics";

export type SortDir = "asc" | "desc";

function isNum(v: number | null | undefined): v is number {
  return v != null && Number.isFinite(v);
}

/**
 * Per-company YoY of `metric` from its own last two fiscal years — percentage POINTS for margins,
 * relative % for levels. Emits a CompareCell (unit "percent") so the existing chart/table render it;
 * a company with <2 rows or non-consecutive years becomes an n.m. cell (the others still plot).
 */
export function companyYoyCell(
  f: FundamentalsOut | undefined,
  metric: string,
  fallback: CompareCell,
): CompareCell {
  const nm = (reason: string): CompareCell => ({
    ...fallback,
    value: { value: null, unit: "percent", reason },
  });
  if (!f || f.rows.length < 2) return nm("Only one fiscal year reported.");
  const latest = f.rows[f.rows.length - 1];
  const prior = f.rows[f.rows.length - 2];
  if (prior.fiscal_year !== latest.fiscal_year - 1)
    return nm("No consecutive prior fiscal year.");
  const cur = metricAt(latest.metrics, metric).value;
  const prev = metricAt(prior.metrics, metric).value;
  const val = MARGIN_KEYS.has(metric)
    ? pointChange(cur, prev)
    : relativeChange(cur, prev);
  if (!isNum(val)) return nm("No comparable prior value.");
  return {
    ticker: fallback.ticker,
    cik: fallback.cik,
    value: { value: val, unit: "percent" },
    fiscal_year: latest.fiscal_year,
    period_end: latest.period_end,
    label: latest.label,
  };
}

/** Ticker order by the LEFT (level) value; n.m. companies always trail. Applied to both charts. */
export function orderTickers(left: CompareCell[], dir: SortDir): string[] {
  const num = left.filter((r) => isNum(r.value.value));
  const nan = left.filter((r) => !isNum(r.value.value));
  num.sort((a, b) =>
    dir === "desc"
      ? (b.value.value as number) - (a.value.value as number)
      : (a.value.value as number) - (b.value.value as number),
  );
  return [...num, ...nan].map((r) => r.ticker);
}

/** Reorder any ticker-keyed rows to match a shared order, so bars align company-to-company. */
export function reorder<T extends { ticker: string }>(
  order: string[],
  rows: T[],
): T[] {
  const ix = new Map(order.map((t, i) => [t, i] as const));
  return [...rows].sort(
    (a, b) => (ix.get(a.ticker) ?? 1e9) - (ix.get(b.ticker) ?? 1e9),
  );
}

export interface CompareValueFormat {
  axis: (v: number) => string;
  label: (cell: CompareCell) => string;
}

/** YoY axis/label formatting for the right chart: pp for margins, signed % for levels. */
export function yoyFormat(metric: string): CompareValueFormat {
  if (MARGIN_KEYS.has(metric)) {
    return {
      axis: (v) => formatPp(v),
      label: (c) => formatPp(c.value.value),
    };
  }
  return {
    axis: (v) => `${v > 0 ? "+" : ""}${Math.round(v * 100)}%`,
    label: (c) => formatSignedPercent(c.value.value),
  };
}
