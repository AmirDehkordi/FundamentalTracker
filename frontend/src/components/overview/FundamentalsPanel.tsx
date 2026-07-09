import { useFundamentals } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { FundamentalsTable } from "@/components/overview/FundamentalsTable";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { METRIC_ROWS } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

// Mirrors FundamentalsTable's actual row structure (group headers + metric rows) so the
// skeleton's height matches the real table and doesn't shove EarningsQuality/CapexIntensity
// down the page once data arrives.
const SKELETON_GROUPS = Array.from(
  new Set(METRIC_ROWS.map((m) => m.group)),
).map((group) => ({
  group,
  rows: METRIC_ROWS.filter((m) => m.group === group).length,
}));

function TableSkeleton() {
  return (
    <div className="w-full">
      <div className="flex h-10 items-center border-b border-border px-2">
        <Skeleton className="h-3.5 w-16" />
      </div>
      {SKELETON_GROUPS.map(({ group, rows }) => (
        <div key={group}>
          <div className="flex h-8 items-end px-2 pb-1 pt-3">
            <Skeleton className="h-3 w-24" />
          </div>
          {Array.from({ length: rows }).map((_, i) => (
            <div
              key={i}
              className="flex h-[34px] items-center border-b border-border px-2"
            >
              <Skeleton className="h-3.5 w-32" />
            </div>
          ))}
        </div>
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
