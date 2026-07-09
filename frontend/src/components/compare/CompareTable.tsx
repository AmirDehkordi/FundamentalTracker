import type { CompareCell } from "@/api/contracts";
import { MetricText } from "@/components/metric/MetricText";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
} from "@/components/ui/table";
import { formatDayMonthYear } from "@/lib/format";
import type { Tone } from "@/lib/metrics";
import { tickerColor } from "@/lib/tickers";
import { cn } from "@/lib/utils";

export interface YoyDisplay {
  text: string;
  tone: Tone;
}

const TONE_CLASS: Record<Tone, string> = {
  pos: "text-pos",
  neg: "text-neg",
  neutral: "text-fg-2",
};

/** Exact values behind the bars, each row labelled with the company's own fiscal year. When the metric
 *  supports it, a trailing column mirrors the right chart's year-over-year change per company. */
export function CompareTable({
  rows,
  signed = false,
  yoyByTicker,
}: {
  rows: CompareCell[];
  signed?: boolean;
  yoyByTicker?: Record<string, YoyDisplay>;
}) {
  const showYoy = yoyByTicker != null;
  return (
    <Table className="text-13">
      <TableHeader>
        <tr className="border-b border-border">
          <TableHead className="text-left text-fg-3">Company</TableHead>
          <TableHead className="text-right text-fg-3">Value</TableHead>
          {showYoy && (
            <TableHead className="text-right text-fg-3">YoY change</TableHead>
          )}
          <TableHead className="text-right text-fg-3">Fiscal year</TableHead>
        </tr>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const yoy = yoyByTicker?.[r.ticker];
          return (
            <tr
              key={r.ticker}
              className="border-b border-border hover:bg-surface-2"
            >
              <TableCell>
                <span className="flex items-center gap-2">
                  <span
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ background: tickerColor(r.ticker) }}
                    aria-hidden
                  />
                  <span className="font-medium tabular-nums text-fg-1">
                    {r.ticker}
                  </span>
                </span>
              </TableCell>
              <TableCell className="text-right">
                <MetricText
                  mv={r.value}
                  className="text-fg-1"
                  signed={signed}
                />
              </TableCell>
              {showYoy && (
                <TableCell className="text-right tabular-nums">
                  <span
                    className={cn(yoy ? TONE_CLASS[yoy.tone] : "text-fg-3")}
                  >
                    {yoy?.text ?? "—"}
                  </span>
                </TableCell>
              )}
              <TableCell className="text-right tabular-nums text-fg-2">
                FY{r.fiscal_year}
                <span className="ml-1 text-fg-3">
                  · {formatDayMonthYear(r.period_end)}
                </span>
              </TableCell>
            </tr>
          );
        })}
      </TableBody>
    </Table>
  );
}
