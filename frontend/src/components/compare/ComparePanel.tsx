import { useCompare } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { CompareChart } from "@/components/compare/CompareChart";
import { CompareTable } from "@/components/compare/CompareTable";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { compareMetricLabel, isSignedMetric } from "@/lib/metrics";

/** Cross-company comparison of one metric: chart + exact-values table + basis caption. */
export function ComparePanel({ metric }: { metric: string }) {
  const query = useCompare(metric);
  const signed = isSignedMetric(metric);

  return (
    <Panel title={compareMetricLabel(metric)}>
      <AsyncBoundary
        query={query}
        skeleton={
          <div className="space-y-4">
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        }
        errorTitle="Couldn't load comparison"
        isEmpty={(d) => d.rows.length === 0}
        empty={<EmptyState>No comparable data for this metric.</EmptyState>}
      >
        {(data) => (
          <div className="space-y-4">
            <CompareChart rows={data.rows} signed={signed} />
            <CompareTable rows={data.rows} signed={signed} />
            <p className="text-xs text-fg-3">{data.basis_note}</p>
          </div>
        )}
      </AsyncBoundary>
    </Panel>
  );
}
