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
    <div>
      <dt className="text-xs text-fg-3">{label}</dt>
      <dd className="text-sm font-medium tabular-nums text-fg-1">{value}</dd>
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
      <div>
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
    <div>
      <dt className="text-xs text-fg-3">{label}</dt>
      <dd
        className={cn(
          "flex items-center gap-0.5 text-sm font-medium tabular-nums",
          tone,
        )}
      >
        {Arrow && <Arrow className="size-3.5" aria-hidden />}
        {text}
      </dd>
    </div>
  );
}

function WindowBlock({ w }: { w: InsiderWindow }) {
  const title = w.days === 90 ? "Last 90 days" : "Last 365 days";
  const empty = w.buy_count === 0 && w.sell_count === 0;
  return (
    <div className="rounded-md border border-border p-3">
      <div className="mb-2 text-xs uppercase tracking-wide text-fg-3">
        {title}
      </div>
      {empty ? (
        <p className="text-13 text-fg-3">No transactions in this window.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
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
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <WindowBlock w={data.window_90d} />
        <WindowBlock w={data.window_365d} />
      </div>
      <p className="text-xs leading-snug text-fg-3">{data.caveat}</p>
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
