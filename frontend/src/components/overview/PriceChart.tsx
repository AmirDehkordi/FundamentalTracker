import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";

import type { PriceRow } from "@/api/contracts";
import { TooltipShell } from "@/components/charts/ChartTooltip";
import { CHART, axisBase, gridProps } from "@/components/charts/chartTheme";
import { formatDayMonthYear, formatPrice } from "@/lib/format";

export interface PriceMarker {
  key: string;
  /** A date string that exactly matches a category tick (snapped to a trading day). */
  x: string;
  label: string;
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function monthTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
}

function PriceTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload as PriceRow;
  return (
    <TooltipShell
      title={formatDayMonthYear(row.date)}
      rows={[
        { label: "Close", value: formatPrice(row.close), color: CHART.accent },
      ]}
    />
  );
}

/** Daily close as a 1.5px accent line + 8% area fill; 10-K filings as dashed reference lines. */
export function PriceChart({
  rows,
  markers,
}: {
  rows: PriceRow[];
  markers: PriceMarker[];
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      {/* Extra top room so the "10-K" reference-line labels aren't clipped. */}
      <AreaChart
        data={rows}
        margin={{ top: 22, right: 12, bottom: 4, left: 4 }}
      >
        <CartesianGrid {...gridProps} />
        <XAxis
          dataKey="date"
          {...axisBase}
          tickFormatter={monthTick}
          minTickGap={48}
        />
        <YAxis
          {...axisBase}
          width={52}
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => `$${Math.round(v)}`}
        />
        <RTooltip
          content={<PriceTooltip />}
          cursor={{ stroke: CHART.grid, strokeDasharray: "3 3" }}
        />
        <Area
          type="monotone"
          dataKey="close"
          stroke={CHART.accent}
          strokeWidth={1.5}
          fill={CHART.accent}
          fillOpacity={0.08}
          dot={false}
          activeDot={{ r: 3, fill: CHART.accent, stroke: CHART.accent }}
          isAnimationActive={false}
        />
        {markers.map((m) => (
          <ReferenceLine
            key={m.key}
            x={m.x}
            stroke={CHART.grid}
            strokeDasharray="4 4"
            label={{
              value: m.label,
              position: "top",
              fontSize: 10,
              fill: CHART.text3,
            }}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
