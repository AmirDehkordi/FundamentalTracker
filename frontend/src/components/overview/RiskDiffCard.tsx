import { ExternalLink } from "lucide-react";

import type { FilingRef, RiskDiffOut, RiskSummaryItem } from "@/api/contracts";
import {
  RISK_SUMMARY_ENABLED,
  useRiskDiff,
  useRiskDiffSummary,
} from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useSelection } from "@/state/selection";

/** One tinted list ("Top new risks" neg, "Top reduced risks" pos): title + one-line detail per item. */
function RiskList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "pos" | "neg";
  items: RiskSummaryItem[];
}) {
  return (
    <div>
      <div
        className={cn(
          "mb-1 text-13 font-medium",
          tone === "neg" ? "text-neg" : "text-pos",
        )}
      >
        {title}
      </div>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className="text-13 leading-snug">
            <span className="font-medium text-fg-1">{it.title}</span>
            <span className="text-fg-3"> — {it.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Lazy LLM summary of the risk-diff. Degrades gracefully (locked decision): a skeleton while loading,
 * and the whole section HIDDEN on any non-200 (503/no-LLM/route-absent). Gated off by default — see
 * RISK_SUMMARY_ENABLED — so it adds nothing until the backend ships the route.
 */
function RiskSummarySection({ ticker }: { ticker: string }) {
  const q = useRiskDiffSummary(ticker);
  if (!RISK_SUMMARY_ENABLED) return null;
  if (q.isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (!q.isSuccess) return null;
  const news = (q.data.new_risks ?? []).slice(0, 3);
  const reduced = (q.data.reduced_risks ?? []).slice(0, 3);
  if (news.length === 0 && reduced.length === 0) return null;
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-surface-2 p-3">
      <div className="text-xs uppercase tracking-wide text-fg-3">
        AI summary
      </div>
      {news.length > 0 && (
        <RiskList title="Top new risks" tone="neg" items={news} />
      )}
      {reduced.length > 0 && (
        <RiskList title="Top reduced risks" tone="pos" items={reduced} />
      )}
    </div>
  );
}

function Section({
  value,
  title,
  count,
  items,
  filing,
}: {
  value: string;
  title: string;
  count: number;
  items: string[];
  filing: FilingRef | null;
}) {
  return (
    <AccordionItem value={value} className="border-border">
      <AccordionTrigger className="py-2 text-13 font-medium text-fg-1">
        <span>
          {title} <span className="tabular-nums text-fg-3">({count})</span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-3">
        {items.length === 0 ? (
          <p className="text-13 text-fg-3">
            No paragraphs {title.toLowerCase()}.
          </p>
        ) : (
          <ScrollArea className="max-h-44 pr-3">
            <ul className="space-y-2">
              {items.map((t, i) => (
                <li key={i} className="text-13 leading-snug text-fg-2">
                  {t}
                </li>
              ))}
            </ul>
          </ScrollArea>
        )}
        {filing && (
          <a
            href={filing.primary_doc_url}
            target="_blank"
            rel="noopener noreferrer"
            className="focus-ring mt-2 inline-flex items-center gap-1 rounded text-xs text-brand hover:underline"
          >
            Read the FY{filing.fiscal_year} 10-K on SEC.gov
            <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </AccordionContent>
    </AccordionItem>
  );
}

function RiskDiffBody({ data }: { data: RiskDiffOut }) {
  if (!data.available) {
    return (
      <p className="text-13 leading-snug text-fg-3">
        {data.note ?? "Year-over-year risk-factor diff is unavailable."}
      </p>
    );
  }
  const { latest, prior, added, removed, counts } = data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2 text-13 text-fg-2">
        <span className="whitespace-nowrap tabular-nums">
          {latest ? `FY${latest.fiscal_year}` : "—"} vs{" "}
          {prior ? `FY${prior.fiscal_year}` : "—"}
        </span>
        <span className="ml-auto shrink-0 whitespace-nowrap tabular-nums">
          <span className="font-medium text-fg-1">{counts.added}</span> added ·{" "}
          <span className="font-medium text-fg-1">{counts.removed}</span>{" "}
          removed
        </span>
      </div>
      <RiskSummarySection ticker={data.ticker} />
      <Accordion type="single" collapsible className="border-t border-border">
        <Section
          value="added"
          title="Added"
          count={counts.added}
          items={added}
          filing={latest}
        />
        <Section
          value="removed"
          title="Removed"
          count={counts.removed}
          items={removed}
          filing={prior}
        />
      </Accordion>
    </div>
  );
}

/** Item 1A additions/removals between the two most recent 10-Ks, with SEC link-outs. */
export function RiskDiffCard() {
  const { ticker } = useSelection();
  const query = useRiskDiff(ticker);

  return (
    <Panel
      title="Risk factors: what changed"
      info="Deterministic year-over-year diff of 10-K Item 1A paragraphs (added/removed, not editorial)."
    >
      <AsyncBoundary
        query={query}
        skeleton={
          <div className="space-y-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        }
        errorTitle="Couldn't load risk-factor diff"
      >
        {(data) => <RiskDiffBody data={data} />}
      </AsyncBoundary>
    </Panel>
  );
}
