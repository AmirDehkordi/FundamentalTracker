import type { ReactNode } from "react";
import { useState } from "react";
import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";

import { useAllFundamentals, useCompare } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { CompareChart } from "@/components/compare/CompareChart";
import { CompareTable } from "@/components/compare/CompareTable";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import {
  companyYoyCell,
  orderTickers,
  reorder,
  type SortDir,
  yoyFormat,
} from "@/lib/compare";
import { describeMetric } from "@/lib/format";
import {
  YOY_ELIGIBLE,
  compareMetricLabel,
  isSignedMetric,
  polarityOf,
  toneForDelta,
} from "@/lib/metrics";

function SortToggle({
  dir,
  onChange,
}: {
  dir: SortDir;
  onChange: (d: SortDir) => void;
}) {
  const desc = dir === "desc";
  return (
    <button
      type="button"
      onClick={() => onChange(desc ? "asc" : "desc")}
      className="focus-ring inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
    >
      {desc ? (
        <ArrowDownWideNarrow className="size-3.5" aria-hidden />
      ) : (
        <ArrowUpNarrowWide className="size-3.5" aria-hidden />
      )}
      {desc ? "High → low" : "Low → high"}
    </button>
  );
}

function ChartSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs uppercase tracking-wide text-fg-3">{title}</div>
      {children}
    </div>
  );
}

/**
 * Cross-company comparison: two aligned charts (latest-FY level + its YoY change) sharing one sort
 * order, an exact-values table, and a basis caption. The YoY chart is derived client-side from each
 * company's own fundamentals (the compare endpoint returns only the level), degrading per-company.
 */
export function ComparePanel({ metric }: { metric: string }) {
  const query = useCompare(metric);
  const signed = isSignedMetric(metric);
  const [dir, setDir] = useState<SortDir>("desc");

  const leftRows = query.data?.rows ?? [];
  const tickers = leftRows.map((r) => r.ticker);
  const all = useAllFundamentals(tickers);
  const yoyEligible = YOY_ELIGIBLE.has(metric);

  return (
    <Panel
      title={compareMetricLabel(metric)}
      actions={<SortToggle dir={dir} onChange={setDir} />}
    >
      <AsyncBoundary
        query={query}
        skeleton={
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <Skeleton className="h-[300px] w-full" />
              <Skeleton className="h-[300px] w-full" />
            </div>
            <Skeleton className="h-32 w-full" />
          </div>
        }
        errorTitle="Couldn't load comparison"
        isEmpty={(d) => d.rows.length === 0}
        empty={<EmptyState>No comparable data for this metric.</EmptyState>}
      >
        {(data) => {
          const order = orderTickers(data.rows, dir);
          const lrows = reorder(order, data.rows);
          const rrows = reorder(
            order,
            data.rows.map((r) =>
              companyYoyCell(all.byTicker[r.ticker], metric, r),
            ),
          );
          // Per-company YoY for the table's change column (only when the metric supports YoY). Colour by
          // the metric's polarity so it reads like the overview (a cost rising is red, not green).
          const pol = polarityOf(metric);
          const yoyByTicker =
            yoyEligible && !all.isPending && !all.allError
              ? Object.fromEntries(
                  rrows.map((c) => {
                    const v = c.value.value;
                    return [
                      c.ticker,
                      v == null
                        ? {
                            text: describeMetric(c.value).text,
                            tone: "neutral" as const,
                          }
                        : {
                            text: yoyFormat(metric).label(c),
                            tone: toneForDelta(v, pol),
                          },
                    ];
                  }),
                )
              : undefined;
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <ChartSection title="Latest fiscal year">
                  <CompareChart rows={lrows} signed={signed} />
                </ChartSection>
                <ChartSection title="Year-over-year change">
                  {!yoyEligible ? (
                    <EmptyState>
                      Year-over-year isn&apos;t meaningful for this metric.
                    </EmptyState>
                  ) : all.isPending ? (
                    <Skeleton className="h-[260px] w-full" />
                  ) : all.allError ? (
                    <EmptyState>Year-over-year data is unavailable.</EmptyState>
                  ) : (
                    <CompareChart
                      rows={rrows}
                      valueFormat={yoyFormat(metric)}
                    />
                  )}
                </ChartSection>
              </div>
              <CompareTable
                rows={lrows}
                signed={signed}
                yoyByTicker={yoyByTicker}
              />
              <p className="text-xs text-fg-3">{data.basis_note}</p>
            </div>
          );
        }}
      </AsyncBoundary>
    </Panel>
  );
}
