import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
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
import { ChartLegend } from "@/components/charts/ChartLegend";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatPercent,
  formatUsd,
  formatUsdCompact,
  pointChange,
} from "@/lib/format";
import { metricAt } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

// Two non-accent hues (sign is shown by geometry from the zero line, so not pos/neg).
const HUES = { rev: "#2DB6A6", op: "#A78BFA" } as const; // teal + violet
const CHART_HEIGHT = 200; // matches EarningsQuality so the FY baselines align

interface IomDatum {
  fy: string;
  dRevUsd: number | null;
  dOpIncUsd: number | null;
  ratioText: string;
  ratioMuted: boolean;
  ratioNote: string | null;
}

// Incremental operating margin = ΔOperating income ÷ ΔRevenue — the SAME quantity the bars encode, so
// chart and number tell one story (NOT the backend operating_leverage elasticity).
function incMargin(dOp: number | null, dRev: number | null) {
  if (dOp == null || dRev == null)
    return {
      text: "n.m.",
      muted: true,
      note: "Missing revenue or operating income.",
    };
  if (dRev <= 0)
    return {
      text: "n.m.",
      muted: true,
      note: "Revenue was flat or down; incremental margin isn't meaningful.",
    };
  return { text: formatPercent(dOp / dRev), muted: false, note: null };
}

/** Per-FY dollar deltas from consecutive rows; non-consecutive FYs are skipped. */
function toData(rows: FundamentalsRow[]): IomDatum[] {
  const out: IomDatum[] = [];
  for (let i = 1; i < rows.length; i++) {
    const cur = rows[i];
    const prev = rows[i - 1];
    if (cur.fiscal_year !== prev.fiscal_year + 1) continue;
    const dRev = pointChange(
      metricAt(cur.metrics, "revenue").value,
      metricAt(prev.metrics, "revenue").value,
    );
    const dOp = pointChange(
      metricAt(cur.metrics, "operating_income").value,
      metricAt(prev.metrics, "operating_income").value,
    );
    const r = incMargin(dOp, dRev);
    out.push({
      fy: `FY${cur.fiscal_year}`,
      dRevUsd: dRev,
      dOpIncUsd: dOp,
      ratioText: r.text,
      ratioMuted: r.muted,
      ratioNote: r.note,
    });
  }
  return out;
}

function IomTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as IomDatum;
  return (
    <TooltipShell
      title={d.fy}
      rows={[
        { label: "Δ Revenue", value: formatUsd(d.dRevUsd), color: HUES.rev },
        {
          label: "Δ Operating income",
          value: formatUsd(d.dOpIncUsd),
          color: HUES.op,
        },
        { label: "Incremental operating margin", value: d.ratioText },
      ]}
      note={d.ratioNote ?? undefined}
    />
  );
}

function IncMarginChart({ rows }: { rows: FundamentalsRow[] }) {
  const data = toData(rows);
  if (data.length === 0) {
    return (
      <EmptyState>
        Not enough consecutive history to compute year-over-year change.
      </EmptyState>
    );
  }
  const sub: Record<string, SubLabel> = Object.fromEntries(
    data.map((d) => [d.fy, { text: d.ratioText, muted: d.ratioMuted }]),
  );

  return (
    <div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ComposedChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid {...gridProps} />
          <XAxis
            dataKey="fy"
            {...axisBase}
            tick={makeFyTick(sub)}
            interval={0}
            height={40}
          />
          <YAxis {...axisBase} width={52} tickFormatter={formatUsdCompact} />
          <ReferenceLine y={0} stroke={CHART.grid} />
          <RTooltip
            content={<IomTooltip />}
            cursor={{ fill: "rgba(224,166,78,0.06)" }}
          />
          <Bar
            dataKey="dRevUsd"
            fill={HUES.rev}
            radius={[2, 2, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
          <Bar
            dataKey="dOpIncUsd"
            fill={HUES.op}
            radius={[2, 2, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { label: "Δ Revenue", color: HUES.rev },
          { label: "Δ Operating income", color: HUES.op },
        ]}
      />
    </div>
  );
}

/** Per-FY dollar change in revenue vs operating income, with the incremental operating margin beneath. */
export function IncrementalOperatingMarginCard() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Incremental operating margin"
      info="Bars: year-over-year change in revenue and operating income (dollars). Below each year: incremental operating margin = Δoperating income ÷ Δrevenue; n.m. when revenue is flat or down."
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[232px] w-full" />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length < 2}
        empty={<EmptyState>Not enough history yet.</EmptyState>}
      >
        {/* slice(-5): up to 4 delta bars need 5 rows (the earliest is the first prior). */}
        {(data) => <IncMarginChart rows={data.rows.slice(-5)} />}
      </AsyncBoundary>
    </Panel>
  );
}
