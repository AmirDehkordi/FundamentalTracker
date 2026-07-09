import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";

import type { CompareCell, MetricUnit } from "@/api/contracts";
import { TooltipShell } from "@/components/charts/ChartTooltip";
import {
  CHART,
  CHART_MARGIN,
  axisBase,
  gridProps,
} from "@/components/charts/chartTheme";
import { makeFyTick, type SubLabel } from "@/components/charts/DualAxisTick";
import type { CompareValueFormat } from "@/lib/compare";
import {
  describeMetric,
  formatDayMonthYear,
  formatPerShare,
  formatPp,
  formatShares,
  formatSignedPercent,
  formatUsdCompact,
} from "@/lib/format";
import { tickerColor } from "@/lib/tickers";

interface CmpDatum {
  ticker: string;
  /** Numeric height driver; null values map to 0 so the "n.m." label anchors at the baseline. */
  barValue: number;
  valueLabel: string;
  fy: string;
  periodEnd: string;
}

function cellLabel(cell: CompareCell, signed: boolean): string {
  if (cell.value.value != null && signed && cell.value.unit === "percent") {
    return formatSignedPercent(cell.value.value);
  }
  return describeMetric(cell.value).text;
}

function axisFormatter(unit: MetricUnit) {
  return (v: number): string => {
    switch (unit) {
      case "USD":
        return formatUsdCompact(v); // "$600B" (no trailing .0) on the axis
      case "USD/shares":
        return formatPerShare(v);
      case "shares":
        return formatShares(v);
      case "percent":
        return `${Math.round(v * 100)}%`;
      case "percentage_points":
        return formatPp(v);
      case "ratio":
        return `${v.toFixed(1)}x`;
    }
  };
}

function CmpTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as CmpDatum;
  return (
    <TooltipShell
      title={d.ticker}
      rows={[{ value: d.valueLabel, color: tickerColor(d.ticker) }]}
      note={`FY${d.fy.replace("FY", "")} · ended ${formatDayMonthYear(d.periodEnd)}`}
    />
  );
}

/** One bar per company in its fixed series colour; x-axis footnotes each with its own fiscal year.
 *  `valueFormat` overrides the unit-based axis/label formatting (used by the YoY chart for pp / signed %). */
export function CompareChart({
  rows,
  signed = false,
  valueFormat,
}: {
  rows: CompareCell[];
  signed?: boolean;
  valueFormat?: CompareValueFormat;
}) {
  const unit = rows[0]?.value.unit ?? "USD";
  const data: CmpDatum[] = rows.map((r) => ({
    ticker: r.ticker,
    // n.m. companies (e.g. NVDA capex) get a 0-height bar so their "n.m." label stays on-canvas at the
    // baseline instead of being extrapolated off the plot area by Recharts.
    barValue: r.value.value ?? 0,
    valueLabel: valueFormat
      ? r.value.value != null
        ? valueFormat.label(r)
        : describeMetric(r.value).text
      : cellLabel(r, signed),
    fy: `FY${r.fiscal_year}`,
    periodEnd: r.period_end,
  }));
  const sub: Record<string, SubLabel> = Object.fromEntries(
    data.map((d) => [d.ticker, { text: d.fy, muted: true }]),
  );

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={CHART_MARGIN}>
        <CartesianGrid {...gridProps} />
        <XAxis
          dataKey="ticker"
          {...axisBase}
          tick={makeFyTick(sub)}
          interval={0}
          height={40}
        />
        <YAxis
          {...axisBase}
          width={52}
          tickFormatter={valueFormat ? valueFormat.axis : axisFormatter(unit)}
        />
        <ReferenceLine y={0} stroke={CHART.grid} />
        <RTooltip
          content={<CmpTooltip />}
          cursor={{ fill: "rgba(224,166,78,0.06)" }}
        />
        <Bar
          dataKey="barValue"
          radius={[2, 2, 0, 0]}
          maxBarSize={64}
          isAnimationActive={false}
        >
          {data.map((d) => (
            <Cell key={d.ticker} fill={tickerColor(d.ticker)} />
          ))}
          <LabelList
            dataKey="valueLabel"
            position="top"
            fontSize={12}
            fill={CHART.text2}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
