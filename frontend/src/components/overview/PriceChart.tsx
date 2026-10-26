import type { ReactNode } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";

import {
  TooltipShell,
  type TooltipRow,
} from "@/components/charts/ChartTooltip";
import { CHART, axisBase, gridProps } from "@/components/charts/chartTheme";
import type { PriceRowMa } from "@/lib/series";
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
  const row = payload[0].payload as PriceRowMa;
  const rows: TooltipRow[] = [
    { label: "Close", value: formatPrice(row.close), color: CHART.accent },
  ];
  if (row.ma150 != null) {
    rows.push({
      label: "150-day MA",
      value: formatPrice(row.ma150),
      color: CHART.text2,
    });
  }
  return <TooltipShell title={formatDayMonthYear(row.date)} rows={rows} />;
}

function LegendItem({ swatch, label }: { swatch: ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-fg-3">
      {swatch}
      {label}
    </span>
  );
}

/**
 * Daily close (1.5px accent line + 8% fill), a dashed 150-day moving average, a low-opacity volume
 * sub-panel in the bottom fifth, a last-price callout, and 10-K filings as dashed reference lines.
 */
export function PriceChart({
  rows,
  markers,
}: {
  rows: PriceRowMa[];
  markers: PriceMarker[];
}) {
  // Inflate the (hidden) volume axis x5 so bars can only ever occupy the bottom ~20% of the plot.
  const volMax = Math.max(1, ...rows.map((r) => r.volume ?? 0));
  const last = rows[rows.length - 1];
  const nearLeftCutoff = rows.length * 0.08;

  return (
    <div className="flex flex-col gap-1.5">
      <ResponsiveContainer width="100%" height={232}>
        {/* Extra top room for the "10-K" labels; extra right room for the last-price callout. */}
        <ComposedChart
          data={rows}
          margin={{ top: 22, right: 56, bottom: 4, left: 4 }}
        >
          <CartesianGrid {...gridProps} />
          <XAxis
            dataKey="date"
            {...axisBase}
            tickFormatter={monthTick}
            minTickGap={48}
          />
          <YAxis
            yAxisId="price"
            {...axisBase}
            width={52}
            domain={["auto", "auto"]}
            allowDecimals={false}
            tickCount={5}
            tickFormatter={(v: number) => `$${Math.round(v)}`}
          />
          {/* Hidden axis just for volume scaling — keeps bars pinned to the lower fifth. */}
          <YAxis yAxisId="volume" hide domain={[0, volMax * 5]} />
          <RTooltip
            content={<PriceTooltip />}
            cursor={{ stroke: CHART.grid, strokeDasharray: "3 3" }}
          />
          {/* Volume first so the price line and MA paint on top of it. */}
          <Bar
            yAxisId="volume"
            dataKey="volume"
            fill={CHART.axis}
            fillOpacity={0.18}
            isAnimationActive={false}
          />
          <Area
            yAxisId="price"
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
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="ma150"
            stroke={CHART.text2}
            strokeWidth={1}
            strokeDasharray="4 3"
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          {markers.map((m) => {
            const idx = rows.findIndex((r) => r.date === m.x);
            const nearLeft = idx >= 0 && idx <= nearLeftCutoff;
            return (
              <ReferenceLine
                key={m.key}
                yAxisId="price"
                x={m.x}
                stroke={CHART.grid}
                strokeDasharray="4 4"
                label={{
                  value: m.label,
                  position: "top",
                  fontSize: 10,
                  fill: CHART.text3,
                  // Nudge a first-marker label inward so it doesn't collide with the y-axis.
                  dx: nearLeft ? 14 : 0,
                }}
              />
            );
          })}
          {last && (
            <ReferenceDot
              yAxisId="price"
              x={last.date}
              y={last.close}
              r={3}
              fill={CHART.accent}
              stroke={CHART.accent}
              label={{
                value: formatPrice(last.close),
                position: "right",
                fontSize: 11,
                fill: CHART.text1,
              }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-3 pl-1">
        <LegendItem
          swatch={
            <span
              className="h-0.5 w-4 rounded-full"
              style={{ backgroundColor: CHART.accent }}
              aria-hidden
            />
          }
          label="Close"
        />
        <LegendItem
          swatch={
            <span
              className="h-0 w-4 border-t border-dashed"
              style={{ borderColor: CHART.text2 }}
              aria-hidden
            />
          }
          label="150-day MA"
        />
        <LegendItem
          swatch={
            <span
              className="h-2.5 w-2 rounded-[1px]"
              style={{ backgroundColor: CHART.axis, opacity: 0.4 }}
              aria-hidden
            />
          }
          label="Volume"
        />
      </div>
    </div>
  );
}
