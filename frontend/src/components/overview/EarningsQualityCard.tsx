import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";

import type { FundamentalsRow } from "@/api/contracts";
import { useFundamentals } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { TooltipShell } from "@/components/charts/ChartTooltip";
import {
  CHART,
  CHART_MARGIN,
  axisBase,
  gridProps,
} from "@/components/charts/chartTheme";
import { makeFyTick, type SubLabel } from "@/components/charts/DualAxisTick";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { describeMetric, formatPercent } from "@/lib/format";
import { metricAt } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

interface EqDatum {
  fy: string;
  fcfMargin: number | null;
  convText: string;
  convNote: string | null;
  convMuted: boolean;
}

function toData(rows: FundamentalsRow[]): EqDatum[] {
  return rows.map((r) => {
    const conv = describeMetric(metricAt(r.metrics, "fcf_conversion"));
    return {
      fy: `FY${r.fiscal_year}`,
      fcfMargin: metricAt(r.metrics, "fcf_margin").value,
      convText: conv.text,
      convNote: conv.missing ? conv.tooltip : null,
      convMuted: conv.missing,
    };
  });
}

function EqTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as EqDatum;
  return (
    <TooltipShell
      title={d.fy}
      rows={[
        {
          label: "FCF margin",
          value: formatPercent(d.fcfMargin),
          color: CHART.accent,
        },
        { label: "FCF conversion", value: d.convText },
      ]}
      note={d.convNote ?? undefined}
    />
  );
}

function EarningsQualityChart({ rows }: { rows: FundamentalsRow[] }) {
  const data = toData(rows);
  // A company with capex never reported (e.g. NVDA here) has no FCF at all — an empty bar chart reads as
  // broken, so state the fact instead.
  if (data.every((d) => d.fcfMargin == null)) {
    return (
      <EmptyState>
        Free cash flow isn&apos;t reported for this company.
      </EmptyState>
    );
  }
  const sub: Record<string, SubLabel> = Object.fromEntries(
    data.map((d) => [d.fy, { text: d.convText, muted: d.convMuted }]),
  );

  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={CHART_MARGIN}>
        <CartesianGrid {...gridProps} />
        <XAxis
          dataKey="fy"
          {...axisBase}
          tick={makeFyTick(sub)}
          interval={0}
          height={40}
        />
        <YAxis
          {...axisBase}
          width={44}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
        />
        <RTooltip
          content={<EqTooltip />}
          cursor={{ fill: "rgba(110,168,254,0.06)" }}
        />
        <Bar
          dataKey="fcfMargin"
          fill={CHART.accent}
          radius={[2, 2, 0, 0]}
          maxBarSize={44}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** FCF margin by FY (bars) with FCF conversion beneath each year. */
export function EarningsQualityCard() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Earnings quality"
      info="Bars: FCF margin. Below each year: FCF conversion (free cash flow ÷ net income)."
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[200px] w-full" />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length < 2}
        empty={<EmptyState>Not enough history yet.</EmptyState>}
      >
        {(data) => <EarningsQualityChart rows={data.rows.slice(-4)} />}
      </AsyncBoundary>
    </Panel>
  );
}
