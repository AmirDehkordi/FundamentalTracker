import { MessageSquareText } from "lucide-react";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Freshness } from "@/components/Freshness";
import { NotReady } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanies, useValuation } from "@/api/queries";
import { useSelection } from "@/state/selection";
import { EM_DASH, formatFyChip, formatRatio, orDash } from "@/lib/format";
import { fullLegalName } from "@/lib/tickers";
import type { TabKey } from "@/App";

/** Universe-scoped header for the Compare tab — a per-company identity/P/E would be misleading there. */
function UniverseHeader({ count }: { count: number | undefined }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="text-sm font-semibold text-fg-1">Universe</span>
      <span className="truncate text-13 text-fg-2">
        {count != null ? `${count} companies` : EM_DASH} · latest completed FYs
      </span>
    </div>
  );
}

export function TopBar({
  activeTab,
  onAskClick,
}: {
  activeTab: TabKey;
  onAskClick: () => void;
}) {
  const { ticker } = useSelection();
  const companies = useCompanies();
  const company = companies.data?.find((c) => c.ticker === ticker) ?? null;
  const valuation = useValuation(ticker);
  const isCompare = activeTab === "compare";

  return (
    <header className="shrink-0 border-b border-border bg-surface-1">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4">
        {isCompare ? (
          <UniverseHeader count={companies.data?.length} />
        ) : (
          <>
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="text-sm font-semibold tabular-nums text-fg-1">
                {orDash(company?.ticker)}
              </span>
              <span className="truncate text-13 text-fg-2">
                {company
                  ? fullLegalName(company.ticker, company.name)
                  : EM_DASH}
              </span>
            </div>

            <div className="hidden items-center rounded-md bg-accent-bg px-2.5 py-1 md:flex">
              <span className="text-xs tabular-nums text-fg-2">
                {company ? formatFyChip(company) : EM_DASH}
              </span>
            </div>

            <div className="hidden items-center gap-1.5 md:flex">
              <span className="text-xs uppercase tracking-wide text-fg-3">
                Trailing P/E
              </span>
              {ticker == null ? (
                // No company selected yet (empty/errored universe) — em dash, never a stuck skeleton.
                <span className="text-sm font-semibold tabular-nums text-fg-3">
                  {EM_DASH}
                </span>
              ) : (
                <AsyncBoundary
                  query={valuation}
                  skeleton={<Skeleton className="h-4 w-12" />}
                  errorTitle="Trailing P/E unavailable"
                  notReady={<NotReady />}
                >
                  {(v) => (
                    <span className="text-sm font-semibold tabular-nums text-fg-1">
                      {formatRatio(v.trailing_pe.value)}
                    </span>
                  )}
                </AsyncBoundary>
              )}
            </div>
          </>
        )}

        <div className="ml-auto flex items-center gap-4">
          {/* Freshness appears ONCE app-wide, here per the design skill's layout map. */}
          <div className="hidden md:block">
            <Freshness />
          </div>
          <Button size="sm" onClick={onAskClick}>
            <MessageSquareText className="size-4" aria-hidden />
            Ask AI Analyst
          </Button>
        </div>
      </div>
    </header>
  );
}
