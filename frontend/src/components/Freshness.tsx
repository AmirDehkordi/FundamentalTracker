import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Skeleton } from "@/components/ui/skeleton";
import { useFreshness } from "@/api/queries";
import { cn } from "@/lib/utils";
import { formatPricesAsOf } from "@/lib/format";

/** Shared "Prices as of …" line. 501 stub today, so it renders a calm not-ready caption. */
export function Freshness({ className }: { className?: string }) {
  const query = useFreshness();
  return (
    <AsyncBoundary
      query={query}
      skeleton={<Skeleton className="h-3.5 w-36" />}
      errorTitle="Freshness unavailable"
      notReady={
        <span className={cn("text-xs tabular-nums text-fg-3", className)}>
          Prices as of —
        </span>
      }
    >
      {(data) => (
        <span className={cn("text-xs tabular-nums text-fg-3", className)}>
          {formatPricesAsOf(data.max_price_date)}
        </span>
      )}
    </AsyncBoundary>
  );
}
