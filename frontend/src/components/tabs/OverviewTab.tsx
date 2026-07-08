import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Overview panels populate in the next chunk; this is the skeleton geometry from the layout map. */
export function OverviewTab() {
  return (
    <div className="space-y-4">
      {/* KPI row — 5 cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-3 h-6 w-24" />
            <Skeleton className="mt-3 h-3 w-20" />
          </Card>
        ))}
      </div>

      {/* fundamentals table 7/12 · price chart 5/12 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card className="p-4 lg:col-span-7">
          <Skeleton className="h-3 w-32" />
          <div className="mt-4 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        </Card>
        <Card className="p-4 lg:col-span-5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-4 h-48 w-full" />
        </Card>
      </div>

      <p className="text-xs text-fg-3">
        Overview panels populate in the next chunk.
      </p>
    </div>
  );
}
