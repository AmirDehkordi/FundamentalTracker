import { type KeyboardEvent, useEffect, useRef } from "react";

import { AsyncBoundary, isEmptyArray } from "@/components/AsyncBoundary";
import { Freshness } from "@/components/Freshness";
import { EmptyState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { CompanyOut } from "@/api/contracts";
import { useCompanies } from "@/api/queries";
import { useSelection } from "@/state/selection";
import { cn } from "@/lib/utils";
import { formatFyBadge } from "@/lib/format";

function CompanyList({ companies }: { companies: CompanyOut[] }) {
  const { ticker, setTicker } = useSelection();
  const itemRefs = useRef<(HTMLLIElement | null)[]>([]);

  // Seed the active company to the first (ticker-ordered) row once the list arrives.
  useEffect(() => {
    if (ticker == null && companies.length > 0) setTicker(companies[0].ticker);
  }, [companies, ticker, setTicker]);

  const activeIndex = Math.max(
    0,
    companies.findIndex((c) => c.ticker === ticker),
  );

  function move(to: number) {
    const i = (to + companies.length) % companies.length;
    setTicker(companies[i].ticker);
    itemRefs.current[i]?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLUListElement>) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        move(activeIndex + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        move(activeIndex - 1);
        break;
      case "Home":
        e.preventDefault();
        move(0);
        break;
      case "End":
        e.preventDefault();
        move(companies.length - 1);
        break;
    }
  }

  return (
    <ul
      role="listbox"
      aria-label="Tracked companies"
      aria-activedescendant={`company-${companies[activeIndex]?.ticker}`}
      onKeyDown={onKeyDown}
      className="flex flex-col gap-0.5 px-2"
    >
      {companies.map((c, i) => {
        const selected = c.ticker === ticker;
        return (
          <li
            key={c.cik}
            id={`company-${c.ticker}`}
            ref={(el) => {
              itemRefs.current[i] = el;
            }}
            role="option"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => setTicker(c.ticker)}
            className={cn(
              "focus-ring relative flex h-10 cursor-pointer items-center gap-2 rounded-md pl-4 pr-3 focus-visible:ring-inset",
              selected ? "bg-accent-bg" : "hover:bg-surface-2",
            )}
          >
            {selected && (
              <span
                className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand"
                aria-hidden
              />
            )}
            <span
              className={cn(
                "text-13 font-semibold tabular-nums",
                selected ? "text-fg-1" : "text-fg-2",
              )}
            >
              {c.ticker}
            </span>
            <span className="truncate text-xs text-fg-3">{c.name}</span>
            <Badge
              variant="outline"
              className="ml-auto shrink-0 border-border font-medium tabular-nums text-fg-3"
            >
              {formatFyBadge(c.latest_fiscal_year)}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}

function SidebarSkeleton() {
  return (
    <div className="flex flex-col gap-0.5 px-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex h-10 items-center gap-2 px-3">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="ml-auto h-4 w-10" />
        </div>
      ))}
    </div>
  );
}

export function Sidebar() {
  const companies = useCompanies();
  return (
    <nav
      aria-label="Companies"
      className="flex h-full w-[232px] shrink-0 flex-col border-r border-border bg-surface-1"
    >
      <div className="flex h-14 shrink-0 items-center px-4">
        <span className="text-sm font-semibold text-fg-1">
          Fundamentals Tracker
        </span>
      </div>
      <Separator />
      <ScrollArea className="flex-1 py-2">
        <AsyncBoundary
          query={companies}
          skeleton={<SidebarSkeleton />}
          errorTitle="Couldn't load companies"
          isEmpty={isEmptyArray}
          empty={
            <EmptyState className="px-4">
              No companies yet — run ingestion to populate the universe.
            </EmptyState>
          }
        >
          {(data) => <CompanyList companies={data} />}
        </AsyncBoundary>
      </ScrollArea>
      <Separator />
      <div className="shrink-0 px-4 py-3">
        <Freshness />
      </div>
    </nav>
  );
}
