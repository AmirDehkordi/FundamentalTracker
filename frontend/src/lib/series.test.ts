import { describe, expect, it } from "vitest";

import type { PriceRow } from "@/api/contracts";
import { withMovingAverage } from "@/lib/series";

const row = (close: number, i: number): PriceRow => ({
  date: `2025-01-${String((i % 28) + 1).padStart(2, "0")}`,
  open: close,
  high: close,
  low: close,
  close,
  volume: 1,
  source: "test",
});

describe("withMovingAverage", () => {
  it("is null until the window fills, then equals the trailing mean", () => {
    const rows = Array.from({ length: 5 }, (_, i) => row(i + 1, i)); // closes 1..5
    const out = withMovingAverage(rows, 3);
    expect(out.map((r) => r.ma150)).toEqual([null, null, 2, 3, 4]);
  });
  it("returns all-null when the series is shorter than the window", () => {
    const rows = Array.from({ length: 2 }, (_, i) => row(i + 1, i));
    expect(withMovingAverage(rows, 3).every((r) => r.ma150 === null)).toBe(
      true,
    );
  });
});
