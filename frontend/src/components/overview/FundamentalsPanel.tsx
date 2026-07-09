import { useFundamentals } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { FundamentalsTable } from "@/components/overview/FundamentalsTable";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelection } from "@/state/selection";

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  );
}

/** Left ~7/12 panel: the annual fundamentals matrix (last up to 4 FYs + latest-FY YoY). */
export function FundamentalsPanel() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <Panel
      title="Fundamentals"
      info="Reported concepts and derived metrics by fiscal year, latest-filed value per (concept, period). † marks a restated value."
    >
      <AsyncBoundary
        query={query}
        skeleton={<TableSkeleton />}
        errorTitle="Couldn't load fundamentals"
        isEmpty={(d) => d.rows.length === 0}
        empty={<EmptyState>No fundamentals reported yet.</EmptyState>}
      >
        {(data) => <FundamentalsTable rows={data.rows.slice(-4)} />}
      </AsyncBoundary>
    </Panel>
  );
}
