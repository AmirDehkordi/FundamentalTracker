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
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { describeMetric, formatSignedPercent } from "@/lib/format";
import { metricAt } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

// Two desaturated hues (not pos/neg — sign is shown by geometry from the zero line).
const OPLEV = { rev: CHART.accent, op: "#A78BFA" } as const;

interface OlDatum {
  fy: string;
  dRev: number | null;
  dOpInc: number | null;
  levText: string;
  levNote: string | null;
  levMuted: boolean;
}

function toData(rows: FundamentalsRow[]): OlDatum[] {
  return rows.map((r) => {
    const lev = describeMetric(metricAt(r.yoy, "operating_leverage"));
    return {
      fy: `FY${r.fiscal_year}`,
      dRev: metricAt(r.yoy, "revenue").value,
      dOpInc: metricAt(r.yoy, "operating_income").value,
      levText: lev.text,
      levNote: lev.missing ? lev.tooltip : null,
      levMuted: lev.missing,
    };
  });
}

function OlTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as OlDatum;
  return (
    <TooltipShell
      title={d.fy}
      rows={[
        {
          label: "Δ Revenue",
          value: formatSignedPercent(d.dRev),
          color: OPLEV.rev,
        },
        {
          label: "Δ Operating income",
          value: formatSignedPercent(d.dOpInc),
          color: OPLEV.op,
        },
        { label: "Operating leverage", value: d.levText },
      ]}
      note={d.levNote ?? undefined}
    />
  );
}

function Legend() {
  const items = [
    { label: "Δ Revenue", color: OPLEV.rev },
    { label: "Δ Operating income", color: OPLEV.op },
  ];
  return (
    <div className="mt-2 flex items-center justify-center gap-4">
      {items.map((it) => (
        <span
          key={it.label}
          className="flex items-center gap-1.5 text-xs text-fg-3"
        >
          <span
            className="size-2 rounded-[2px]"
            style={{ background: it.color }}
            aria-hidden
          />
          {it.label}
        </span>
      ))}
    </div>
  );
}

function OperatingLeverageChart({ rows }: { rows: FundamentalsRow[] }) {
  const data = toData(rows);
  const sub: Record<string, SubLabel> = Object.fromEntries(
    data.map((d) => [d.fy, { text: d.levText, muted: d.levMuted }]),
  );

  return (
    <div>
      <ResponsiveContainer width="100%" height={180}>
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
          <ReferenceLine y={0} stroke={CHART.grid} />
          <RTooltip
            content={<OlTooltip />}
            cursor={{ fill: "rgba(110,168,254,0.06)" }}
          />
          <Bar
            dataKey="dRev"
            fill={OPLEV.rev}
            radius={[2, 2, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
          <Bar
            dataKey="dOpInc"
            fill={OPLEV.op}
            radius={[2, 2, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <Legend />
    </div>
  );
}

/** ΔOperating income vs ΔRevenue per FY, with the operating-leverage ratio beneath each year. */
export function OperatingLeverageCard() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Operating leverage"
      info="Year-over-year change in operating income vs revenue. Leverage = ΔOperating income ÷ ΔRevenue; n.m. when revenue is flat/down or operating income changes sign."
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[200px] w-full" />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length < 2}
        empty={<EmptyState>Not enough history yet.</EmptyState>}
      >
        {(data) => <OperatingLeverageChart rows={data.rows.slice(-4)} />}
      </AsyncBoundary>
    </Panel>
  );
}
