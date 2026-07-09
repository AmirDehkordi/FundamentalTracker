// Pure client-side price-series transforms. Kept out of components so the moving average can be
// computed once over the FULL series and memoized before any range slicing.
import type { PriceRow } from "@/api/contracts";

export interface PriceRowMa extends PriceRow {
  /** Trailing simple MA of `close`; null until `window` observations exist. */
  ma150: number | null;
}

/**
 * Attach a trailing simple moving average of `close` to each row (O(n) rolling sum). `ma150` is null
 * for the first `window-1` rows so the overlay only starts where enough history exists. Compute over
 * the full 2y series, THEN slice — a sliced 1M view still carries a defined MA because its rows'
 * predecessors survive in the full array.
 */
export function withMovingAverage(
  rows: PriceRow[],
  window = 150,
): PriceRowMa[] {
  let sum = 0;
  return rows.map((r, i) => {
    sum += r.close;
    if (i >= window) sum -= rows[i - window].close;
    return { ...r, ma150: i >= window - 1 ? sum / window : null };
  });
}
