import { ArrowDown, ArrowUp } from "lucide-react";

import type { InsiderSummaryOut, InsiderWindow } from "@/api/contracts";
import { useInsider } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { EM_DASH, formatShares, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSelection } from "@/state/selection";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 text-center">
      <dt className="text-xs text-fg-3">{label}</dt>
      <dd className="whitespace-nowrap text-sm font-medium tabular-nums text-fg-1">
        {value}
      </dd>
    </div>
  );
}

/** Net buy/sell direction (buys positive): arrow + sign + colour. Null = unpriced/indeterminate. */
function SignedStat({
  label,
  value,
  kind,
  nullTip,
}: {
  label: string;
  value: number | null;
  kind: "shares" | "usd";
  nullTip: string;
}) {
  if (value == null) {
    return (
      <div className="flex flex-col items-center gap-0.5 text-center">
        <dt className="text-xs text-fg-3">{label}</dt>
        <dd>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help text-sm text-fg-3 underline decoration-fg-3 decoration-dotted underline-offset-2">
                {EM_DASH}
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{nullTip}</TooltipContent>
          </Tooltip>
        </dd>
      </div>
    );
  }
  const tone = value > 0 ? "text-pos" : value < 0 ? "text-neg" : "text-fg-1";
  const Arrow = value > 0 ? ArrowUp : value < 0 ? ArrowDown : null;
  const text = kind === "usd" ? formatUsd(value) : `${formatShares(value)} sh`;
  return (
    <div className="flex flex-col items-center gap-0.5 text-center">
      <dt className="text-xs text-fg-3">{label}</dt>
      <dd
        className={cn(
          "flex items-center justify-center gap-0.5 whitespace-nowrap text-sm font-medium tabular-nums",
          tone,
        )}
      >
        {Arrow && <Arrow className="size-3.5 shrink-0" aria-hidden />}
        {text}
      </dd>
    </div>
  );
}

/** Two windows collapse to one when the 365d aggregates equal the 90d ones AND there's actually
 *  activity to show (all activity is recent) — two empty windows are not "recent activity". */
function windowsEqual(a: InsiderWindow, b: InsiderWindow): boolean {
  return (
    (a.buy_count > 0 || a.sell_count > 0) &&
    a.buy_count === b.buy_count &&
    a.sell_count === b.sell_count &&
    a.net_shares === b.net_shares &&
    a.net_notional === b.net_notional
  );
}

function WindowBlock({ w, title }: { w: InsiderWindow; title?: string }) {
  const heading = title ?? (w.days === 90 ? "Last 90 days" : "Last 365 days");
  const empty = w.buy_count === 0 && w.sell_count === 0;
  return (
    <div className="rounded-md border border-border p-3">
      <div className="mb-2 text-xs uppercase tracking-wide text-fg-3">
        {heading}
      </div>
      {empty ? (
        <p className="text-13 text-fg-3">No transactions in this window.</p>
      ) : (
        <dl className="grid grid-cols-2 justify-items-center gap-x-6 gap-y-4">
          <Stat label="Buys" value={String(w.buy_count)} />
          <Stat label="Sells" value={String(w.sell_count)} />
          <SignedStat
            label="Net shares"
            value={w.net_shares}
            kind="shares"
            nullTip="Indeterminate — missing share counts."
          />
          <SignedStat
            label="Net notional"
            value={w.net_notional}
            kind="usd"
            nullTip="No priced transactions in this window."
          />
        </dl>
      )}
    </div>
  );
}

function InsiderBody({
  data,
  ticker,
}: {
  data: InsiderSummaryOut;
  ticker: string;
}) {
  if (!data.has_data) {
    return (
      <div className="flex h-full flex-col">
        <p className="text-13 text-fg-3">
          No Form 4 insider transactions on file for {ticker}.
        </p>
      </div>
    );
  }
  const collapsed = windowsEqual(data.window_90d, data.window_365d);
  return (
    <div className="flex flex-col gap-2">
      {collapsed ? (
        <>
          <WindowBlock w={data.window_365d} title="Insider transactions" />
          <p className="text-xs text-fg-3">
            All activity within the last 90 days.
          </p>
        </>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <WindowBlock w={data.window_90d} />
          <WindowBlock w={data.window_365d} />
        </div>
      )}
      {data.history_capped && (
        <p className="text-xs text-fg-3">
          Only the most recently filed transactions are ingested — earlier
          insider activity may exist but isn&apos;t reflected here.
        </p>
      )}
    </div>
  );
}

/** Form 4 buys vs sells over 90d / 365d windows with net notional; muted when there's no activity. */
export function InsiderCard() {
  const { ticker } = useSelection();
  const query = useInsider(ticker);

  return (
    <Panel
      title="Insider activity"
      info="Form 4 open-market buys (code P) vs sells (code S). Windows anchor to the latest filing, not today."
      fillHeight={false}
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[128px] w-full" />}
        errorTitle="Couldn't load insider activity"
      >
        {(data) => <InsiderBody data={data} ticker={ticker ?? ""} />}
      </AsyncBoundary>
    </Panel>
  );
}
