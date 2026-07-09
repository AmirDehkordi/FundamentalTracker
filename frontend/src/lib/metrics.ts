// Metric vocabulary and display ordering. Labels are a feature (the skill: "the label is a feature, not
// clutter"), so they live here in sentence case, in the backend's insertion order.

import type { MetricValue } from "@/api/contracts";

/** Read a metric cell, falling back to a null cell if the key is absent (keeps components crash-proof). */
export function metricAt(
  dict: Record<string, MetricValue>,
  key: string,
): MetricValue {
  return dict[key] ?? { value: null, unit: "ratio" };
}

export type MetricGroup = "income" | "cash" | "shares" | "ratio";

/** Where the fundamentals table reads a row's per-FY values from. */
export type ValueSource = "metrics" | "yoy";

/**
 * How the trailing "YoY (latest)" column is derived for a row:
 *  - "relative"   — read latest row's yoy[key] (backend relative %). Level metrics.
 *  - "margin-rel" — relative % of metrics[key] latest vs prior FY (margins have no backend yoy cell).
 *  - "none"       — em dash + tooltip (a YoY-of-a-ratio isn't meaningful).
 */
export type YoyKind = "relative" | "margin-rel" | "none";

export interface MetricRow {
  key: string;
  label: string;
  group: MetricGroup;
  valueSource: ValueSource;
  yoyKind: YoyKind;
}

// Fundamentals table rows, in display order. operating_leverage is the one row read from `yoy` (it is
// inherently a per-FY year-over-year ratio, absent from `metrics`).
export const METRIC_ROWS: MetricRow[] = [
  {
    key: "revenue",
    label: "Revenue",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "cost_of_revenue",
    label: "Cost of revenue",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "gross_profit",
    label: "Gross profit",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "operating_income",
    label: "Operating income",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "net_income",
    label: "Net income",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "eps_diluted",
    label: "Diluted EPS",
    group: "income",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "cfo",
    label: "Cash from operations",
    group: "cash",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "capex",
    label: "Capital expenditure",
    group: "cash",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "fcf",
    label: "Free cash flow",
    group: "cash",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "shares_diluted",
    label: "Diluted shares",
    group: "shares",
    valueSource: "metrics",
    yoyKind: "relative",
  },
  {
    key: "gross_margin",
    label: "Gross margin",
    group: "ratio",
    valueSource: "metrics",
    yoyKind: "margin-rel",
  },
  {
    key: "operating_margin",
    label: "Operating margin",
    group: "ratio",
    valueSource: "metrics",
    yoyKind: "margin-rel",
  },
  {
    key: "net_margin",
    label: "Net margin",
    group: "ratio",
    valueSource: "metrics",
    yoyKind: "margin-rel",
  },
  {
    key: "fcf_margin",
    label: "FCF margin",
    group: "ratio",
    valueSource: "metrics",
    yoyKind: "margin-rel",
  },
  {
    key: "fcf_conversion",
    label: "FCF conversion",
    group: "ratio",
    valueSource: "metrics",
    yoyKind: "none",
  },
  {
    key: "operating_leverage",
    label: "Operating leverage",
    group: "ratio",
    valueSource: "yoy",
    yoyKind: "none",
  },
];

export const GROUP_LABELS: Record<MetricGroup, string> = {
  income: "Income statement",
  cash: "Cash flow",
  shares: "Shares",
  ratio: "Margins & ratios",
};

/** A compare metric that is a signed year-over-year change (render with a leading + on gains). */
export function isSignedMetric(metric: string): boolean {
  return metric.endsWith("_yoy");
}

// Compare tab metric selector — exactly the backend's SUPPORTED_METRICS (9 canonical + 7 derived),
// grouped. `fcf` is intentionally absent: the backend does not expose it as a comparable metric.
export interface CompareMetricGroup {
  label: string;
  options: { value: string; label: string }[];
}

export const COMPARE_METRIC_GROUPS: CompareMetricGroup[] = [
  {
    label: "Income statement",
    options: [
      { value: "revenue", label: "Revenue" },
      { value: "cost_of_revenue", label: "Cost of revenue" },
      { value: "gross_profit", label: "Gross profit" },
      { value: "operating_income", label: "Operating income" },
      { value: "net_income", label: "Net income" },
      { value: "eps_diluted", label: "Diluted EPS" },
    ],
  },
  {
    label: "Cash flow",
    options: [
      { value: "cfo", label: "Cash from operations" },
      { value: "capex", label: "Capital expenditure" },
    ],
  },
  {
    label: "Shares",
    options: [{ value: "shares_diluted", label: "Diluted shares" }],
  },
  {
    label: "Margins & ratios",
    options: [
      { value: "gross_margin", label: "Gross margin" },
      { value: "operating_margin", label: "Operating margin" },
      { value: "net_margin", label: "Net margin" },
      { value: "fcf_margin", label: "FCF margin" },
      { value: "fcf_conversion", label: "FCF conversion" },
      { value: "operating_leverage", label: "Operating leverage" },
    ],
  },
  {
    label: "Growth",
    options: [{ value: "revenue_yoy", label: "Revenue growth (YoY)" }],
  },
];

export const DEFAULT_COMPARE_METRIC = "revenue";

/** Flat lookup of a compare metric's label. */
export function compareMetricLabel(value: string): string {
  for (const g of COMPARE_METRIC_GROUPS) {
    const hit = g.options.find((o) => o.value === value);
    if (hit) return hit.label;
  }
  return value;
}
