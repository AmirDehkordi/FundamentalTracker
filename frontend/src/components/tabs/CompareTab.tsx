import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Cross-company comparison populates in the next chunk; skeleton placeholder for now. */
export function CompareTab() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-fg-3">
          Metric
        </span>
        <Skeleton className="h-8 w-40" />
      </div>
      <Card className="p-4">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="mt-4 h-64 w-full" />
      </Card>
      <p className="text-xs text-fg-3">
        Cross-company comparison populates in the next chunk.
      </p>
    </div>
  );
}
