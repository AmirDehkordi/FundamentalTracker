import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Skeleton } from "@/components/ui/skeleton";
import { useFreshness } from "@/api/queries";
import { formatPricesAsOf } from "@/lib/format";

/** Shared "Prices as of …" line. 501 stub today, so it renders a calm not-ready caption.
 *  Responsive visibility is the caller's job (wrap it) so every state is hidden together. */
export function Freshness() {
  const query = useFreshness();
  return (
    <AsyncBoundary
      query={query}
      skeleton={<Skeleton className="h-3.5 w-36" />}
      errorTitle="Freshness unavailable"
      notReady={
        <span className="text-xs tabular-nums text-fg-3">Prices as of —</span>
      }
    >
      {(data) => (
        <span className="text-xs tabular-nums text-fg-3">
          {formatPricesAsOf(data.max_price_date)}
        </span>
      )}
    </AsyncBoundary>
  );
}
