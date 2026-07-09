import { useState } from "react";

import type { FilingMarker, PriceRow } from "@/api/contracts";
import { usePrices } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { PriceChart, type PriceMarker } from "@/components/overview/PriceChart";
import {
  PRICE_RANGES,
  RangeSelector,
  type RangeKey,
} from "@/components/overview/RangeSelector";
import { EmptyState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { withMovingAverage } from "@/lib/series";
import { useSelection } from "@/state/selection";

const DAY = 86_400_000;
// Matches the backend's _RANGE_DAYS so the client window equals the server basis to the day.
const RANGE_DAYS: Record<RangeKey, number> = {
  "1m": 31,
  "6m": 183,
  "1y": 366,
  max: Number.POSITIVE_INFINITY,
};

/** Slice the full 2y series back from the latest stored trading date (never "today"). Generic so the
 *  moving-average field survives the slice. */
function sliceRows<T extends PriceRow>(rows: T[], range: RangeKey): T[] {
  if (rows.length === 0) return rows;
  const days = RANGE_DAYS[range];
  if (!Number.isFinite(days)) return rows;
  const cutoff = Date.parse(rows[rows.length - 1].date) - days * DAY;
  return rows.filter((r) => Date.parse(r.date) >= cutoff);
}

/** Keep only filings inside the visible window and snap each to the first trading day >= filed, so the
 *  reference line lands on an existing category tick (a category axis won't render an x it doesn't have). */
function snapMarkers(
  visible: PriceRow[],
  filings: FilingMarker[],
): PriceMarker[] {
  if (visible.length === 0) return [];
  const first = Date.parse(visible[0].date);
  const last = Date.parse(visible[visible.length - 1].date);
  const out: PriceMarker[] = [];
  for (const f of filings) {
    const t = Date.parse(f.filed);
    if (t < first || t > last) continue;
    const hit =
      visible.find((r) => Date.parse(r.date) >= t) ??
      visible[visible.length - 1];
    out.push({ key: f.accession, x: hit.date, label: "10-K" });
  }
  return out;
}

/** Right ~5/12 panel: price line with a range selector and 10-K filing reference lines. */
export function PriceChartPanel() {
  const { ticker } = useSelection();
  const [range, setRange] = useState<RangeKey>("1y");
  const query = usePrices(ticker);

  return (
    <Panel
      title="Price"
      info="Daily close from the latest stored trading date; dashed lines mark 10-K filing dates."
      actions={<RangeSelector value={range} onChange={setRange} />}
    >
      <AsyncBoundary
        query={query}
        skeleton={<Skeleton className="h-[256px] w-full" />}
        errorTitle="Couldn't load prices"
        isEmpty={(d) => d.rows.length === 0}
        empty={<EmptyState>No price history for this range.</EmptyState>}
      >
        {(data) => {
          // MA is computed over the FULL series first, then sliced, so a short range still shows it.
          const visible = sliceRows(withMovingAverage(data.rows), range);
          if (visible.length === 0) {
            const known =
              PRICE_RANGES.find((r) => r.key === range)?.label ?? range;
            return (
              <EmptyState>No price history in the last {known}.</EmptyState>
            );
          }
          return (
            <PriceChart
              rows={visible}
              markers={snapMarkers(visible, data.filings)}
            />
          );
        }}
      </AsyncBoundary>
    </Panel>
  );
}
