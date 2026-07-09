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
import { makeFyTick } from "@/components/charts/DualAxisTick";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { describeMetric, formatPercent } from "@/lib/format";
import { metricAt } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

// Paired with OperatingLeverage/IncrementalOperatingMargin: identical container height (200) + margin +
// XAxis height (40) so both FY category axes land on one baseline.
const CHART_HEIGHT = 200;

interface EqDatum {
  fy: string;
  fcfMargin: number | null;
  convText: string;
  convNote: string | null;
}

function toData(rows: FundamentalsRow[]): EqDatum[] {
  return rows.map((r) => {
    const conv = describeMetric(metricAt(r.metrics, "fcf_conversion"));
    return {
      fy: `FY${r.fiscal_year}`,
      fcfMargin: metricAt(r.metrics, "fcf_margin").value,
      convText: conv.text,
      convNote: conv.missing ? conv.tooltip : null,
    };
  });
}

// Round y ticks at 10-point steps up to the rounded max (at least 40%), so gridlines read 0/10/20/30/40%.
function roundTicks(data: EqDatum[]): { ticks: number[]; top: number } {
  const max = Math.max(0, ...data.map((d) => d.fcfMargin ?? 0));
  const top = Math.max(0.4, Math.ceil(max / 0.1) * 0.1);
  const ticks: number[] = [];
  for (let t = 0; t <= top + 1e-9; t += 0.1) ticks.push(Number(t.toFixed(2)));
  return { ticks, top };
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
  const { ticks, top } = roundTicks(data);

  return (
    <div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ComposedChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid {...gridProps} />
          {/* Single-line FY axis (conversion moved off the ticks into the legend/tooltip); height 40 to
              align its baseline with the incremental-margin card's two-line axis. */}
          <XAxis
            dataKey="fy"
            {...axisBase}
            tick={makeFyTick({})}
            interval={0}
            height={40}
          />
          <YAxis
            {...axisBase}
            width={44}
            domain={[0, top]}
            ticks={ticks}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          />
          <RTooltip
            content={<EqTooltip />}
            cursor={{ fill: "rgba(224,166,78,0.06)" }}
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
      <ChartLegend
        items={[
          { label: "FCF margin", color: CHART.accent },
          { label: "FCF conversion — on hover", color: CHART.text3 },
        ]}
      />
    </div>
  );
}

/** FCF margin by FY (bars), round y ticks; FCF conversion is labelled in the legend and shown on hover. */
export function EarningsQualityCard() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Earnings quality"
      info="Bars: FCF margin (free cash flow ÷ revenue). FCF conversion (free cash flow ÷ net income) on hover."
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[232px] w-full" />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length < 2}
        empty={<EmptyState>Not enough history yet.</EmptyState>}
      >
        {(data) => <EarningsQualityChart rows={data.rows.slice(-4)} />}
      </AsyncBoundary>
    </Panel>
  );
}
