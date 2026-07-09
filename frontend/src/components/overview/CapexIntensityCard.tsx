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

// Paired with EarningsQuality: identical container height (200) + margin + XAxis height (40) so both
// FY category axes land on one baseline.
const CHART_HEIGHT = 200;

interface CapexDatum {
  fy: string;
  capexIntensity: number | null;
  reinvestText: string;
  reinvestNote: string | null;
}

function toData(rows: FundamentalsRow[]): CapexDatum[] {
  return rows.map((r) => {
    const reinvest = describeMetric(metricAt(r.metrics, "reinvestment_ratio"));
    return {
      fy: `FY${r.fiscal_year}`,
      capexIntensity: metricAt(r.metrics, "capex_intensity").value,
      reinvestText: reinvest.text,
      reinvestNote: reinvest.missing ? reinvest.tooltip : null,
    };
  });
}

// Round y ticks at 5-point steps up to the rounded max (at least 10%), so gridlines read 0/5/10/15%.
function roundTicks(data: CapexDatum[]): { ticks: number[]; top: number } {
  const max = Math.max(0, ...data.map((d) => d.capexIntensity ?? 0));
  const top = Math.max(0.1, Math.ceil(max / 0.05) * 0.05);
  const ticks: number[] = [];
  for (let t = 0; t <= top + 1e-9; t += 0.05) ticks.push(Number(t.toFixed(3)));
  return { ticks, top };
}

function CapexTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as CapexDatum;
  return (
    <TooltipShell
      title={d.fy}
      rows={[
        {
          label: "Capex intensity",
          value: formatPercent(d.capexIntensity),
          color: CHART.accent,
        },
        { label: "Capex / CFO", value: d.reinvestText },
      ]}
      note={d.reinvestNote ?? undefined}
    />
  );
}

function CapexIntensityChart({ rows }: { rows: FundamentalsRow[] }) {
  const data = toData(rows);
  if (data.every((d) => d.capexIntensity == null)) {
    return (
      <div
        className="flex items-center justify-center text-center"
        style={{ height: CHART_HEIGHT }}
      >
        <EmptyState>Capex isn&apos;t reported for this company.</EmptyState>
      </div>
    );
  }
  const { ticks, top } = roundTicks(data);

  return (
    <div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ComposedChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid {...gridProps} />
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
            content={<CapexTooltip />}
            cursor={{ fill: "rgba(224,166,78,0.06)" }}
          />
          <Bar
            dataKey="capexIntensity"
            fill={CHART.accent}
            radius={[2, 2, 0, 0]}
            maxBarSize={44}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { label: "Capex intensity", color: CHART.accent },
          { label: "Capex / CFO (on hover)", color: CHART.text3 },
        ]}
      />
    </div>
  );
}

/** Capex intensity (capex ÷ revenue) by FY, round y ticks; capex / CFO (reinvestment ratio) on hover. */
export function CapexIntensityCard() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Capex intensity"
      info="Cash capex as reported in the 10-K cash flow statement; finance-lease funded build-out is excluded. For NVDA this line includes intangible-asset purchases per its 10-K."
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[232px] w-full" />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length < 2}
        empty={<EmptyState>Not enough history yet.</EmptyState>}
      >
        {(data) => <CapexIntensityChart rows={data.rows.slice(-4)} />}
      </AsyncBoundary>
    </Panel>
  );
}
