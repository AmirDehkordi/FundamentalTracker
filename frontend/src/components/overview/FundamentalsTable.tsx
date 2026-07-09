import { Fragment } from "react";

import type { FundamentalsRow } from "@/api/contracts";
import { MetricText } from "@/components/metric/MetricText";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  EM_DASH,
  formatDayMonthYear,
  formatPp,
  formatSignedPercent,
  pointChange,
} from "@/lib/format";
import {
  GROUP_LABELS,
  METRIC_ROWS,
  type MetricGroup,
  type MetricRow,
  type Polarity,
  metricAt,
  polarityOf,
  toneForDelta,
} from "@/lib/metrics";
import { cn } from "@/lib/utils";

const NONE_TOOLTIP: Record<string, string> = {
  fcf_conversion: "No year-over-year — a ratio has no meaningful YoY.",
  incremental_operating_margin:
    "Incremental operating margin is itself a year-over-year measure.",
};

const STICKY =
  "sticky left-0 z-10 bg-surface-1 group-hover:bg-surface-2 min-w-[168px]";

interface YoyDescriptor {
  fraction: number | null;
  /** "pp" for margins (point delta), "pct" (relative %) otherwise. */
  unit: "pct" | "pp";
  polarity: Polarity;
  nmReason?: string | null;
  emptyTooltip?: string;
}

/** What the trailing YoY(latest) column shows for a given metric row. */
function yoyForRow(
  meta: MetricRow,
  latest: FundamentalsRow,
  prior: FundamentalsRow | undefined,
): YoyDescriptor {
  const polarity = polarityOf(meta.key);
  if (meta.yoyKind === "none") {
    return {
      fraction: null,
      unit: "pct",
      polarity,
      emptyTooltip: NONE_TOOLTIP[meta.key],
    };
  }
  if (meta.yoyKind === "relative") {
    const mv = metricAt(latest.yoy, meta.key);
    return { fraction: mv.value, unit: "pct", polarity, nmReason: mv.reason };
  }
  // margin-pp: percentage-point change vs the prior consecutive FY (margins carry no backend YoY cell).
  const hasPrior =
    prior != null && prior.fiscal_year === latest.fiscal_year - 1;
  const fraction = hasPrior
    ? pointChange(
        metricAt(latest.metrics, meta.key).value,
        metricAt(prior.metrics, meta.key).value,
      )
    : null;
  if (fraction != null) return { fraction, unit: "pp", polarity };
  return {
    fraction: null,
    unit: "pp",
    polarity,
    emptyTooltip: "No comparable prior fiscal year.",
  };
}

function TooltippedDash({ text, tip }: { text: string; tip: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help text-fg-3 underline decoration-fg-3 decoration-dotted underline-offset-2">
          {text}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{tip}</TooltipContent>
    </Tooltip>
  );
}

const TONE_CLASS = {
  pos: "text-pos",
  neg: "text-neg",
  neutral: "text-fg-2",
} as const;

function YoyCell({
  fraction,
  unit,
  polarity,
  nmReason,
  emptyTooltip,
}: YoyDescriptor) {
  if (fraction != null && Number.isFinite(fraction)) {
    const tone = TONE_CLASS[toneForDelta(fraction, polarity)];
    return (
      <span className={cn("tabular-nums", tone)}>
        {unit === "pp" ? formatPp(fraction) : formatSignedPercent(fraction)}
      </span>
    );
  }
  if (nmReason) return <TooltippedDash text="n.m." tip={nmReason} />;
  if (emptyTooltip) return <TooltippedDash text={EM_DASH} tip={emptyTooltip} />;
  return <span className="text-fg-3">{EM_DASH}</span>;
}

/** Annual matrix: rows = metrics (reported + derived), columns = up to 4 recent FYs + a latest-FY YoY. */
export function FundamentalsTable({ rows }: { rows: FundamentalsRow[] }) {
  const latest = rows[rows.length - 1];
  const prior = rows[rows.length - 2];
  const cols = rows.length + 2; // metric label + FY columns + YoY

  let lastGroup: MetricGroup | null = null;

  return (
    <Table className="text-13">
      <TableHeader>
        <tr className="border-b border-border">
          <TableHead className={cn(STICKY, "text-left align-bottom text-fg-3")}>
            Metric
          </TableHead>
          {rows.map((r) => (
            <TableHead key={r.fiscal_year} className="text-right align-bottom">
              <div className="flex flex-col items-end leading-tight">
                <span className="font-medium text-fg-2">FY{r.fiscal_year}</span>
                <span className="font-normal text-fg-3">
                  ended {formatDayMonthYear(r.period_end)}
                </span>
              </div>
            </TableHead>
          ))}
          <TableHead className="text-right align-bottom">
            <div className="flex flex-col items-end leading-tight">
              <span className="font-medium text-fg-2">YoY</span>
              <span className="font-normal text-fg-3">(latest FY)</span>
            </div>
          </TableHead>
        </tr>
      </TableHeader>
      <TableBody>
        {METRIC_ROWS.map((meta) => {
          const showGroup = meta.group !== lastGroup;
          lastGroup = meta.group;
          const yoy = yoyForRow(meta, latest, prior);
          return (
            <Fragment key={meta.key}>
              {showGroup && (
                <tr>
                  <td
                    colSpan={cols}
                    className="border-b border-border bg-surface-1 px-2 pb-1 pt-3 text-xs uppercase tracking-wide text-fg-3"
                  >
                    {GROUP_LABELS[meta.group]}
                  </td>
                </tr>
              )}
              <tr className="group border-b border-border hover:bg-surface-2">
                <td className={cn(STICKY, "px-2 py-2 text-fg-2")}>
                  {meta.label}
                </td>
                {rows.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right">
                    <MetricText
                      mv={metricAt(
                        meta.valueSource === "yoy" ? r.yoy : r.metrics,
                        meta.key,
                      )}
                      className="text-fg-1"
                    />
                  </TableCell>
                ))}
                <TableCell className="text-right">
                  <YoyCell {...yoy} />
                </TableCell>
              </tr>
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
