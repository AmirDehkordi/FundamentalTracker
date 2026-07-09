import { describe, expect, it } from "vitest";

import type { MetricValue } from "@/api/contracts";
import {
  EM_DASH,
  describeMetric,
  formatDayMonthYear,
  formatFyBadge,
  formatMetric,
  formatPercent,
  formatPerShare,
  formatPp,
  formatShares,
  formatSignedPercent,
  formatUsd,
  formatUsdCompact,
  pointChange,
  relativeChange,
} from "@/lib/format";

const mv = (over: Partial<MetricValue>): MetricValue => ({
  value: null,
  unit: "USD",
  ...over,
});

describe("formatUsd", () => {
  it("scales into B / M and keeps 1 dp for billions", () => {
    expect(formatUsd(1.305e11)).toBe("$130.5B");
    expect(formatUsd(9.64e8)).toBe("$964M");
    expect(formatUsd(1e9)).toBe("$1.0B"); // boundary
  });
  it("covers every magnitude branch and its lower boundary", () => {
    expect(formatUsd(1e12)).toBe("$1.0T"); // T boundary
    expect(formatUsd(2.5e12)).toBe("$2.5T");
    expect(formatUsd(1e6)).toBe("$1M"); // M boundary (whole millions)
    expect(formatUsd(4.2e3)).toBe("$4.2K"); // K branch
    expect(formatUsd(950)).toBe("$950.00"); // sub-1e3 falls through to 2 dp
  });
  it("is sign-aware and guards null / NaN", () => {
    expect(formatUsd(-2.4e9)).toBe("-$2.4B");
    expect(formatUsd(-500)).toBe("-$500.00");
    expect(formatUsd(null)).toBe(EM_DASH);
    expect(formatUsd(Number.NaN)).toBe(EM_DASH);
  });
});

describe("percent helpers", () => {
  it("formatPercent is unsigned (negatives keep their minus)", () => {
    expect(formatPercent(0.624)).toBe("62.4%");
    expect(formatPercent(-0.05)).toBe("-5.0%");
  });
  it("formatSignedPercent forces a + on gains", () => {
    expect(formatSignedPercent(0.114)).toBe("+11.4%");
    expect(formatSignedPercent(-0.032)).toBe("-3.2%");
    expect(formatSignedPercent(null)).toBe(EM_DASH);
  });
});

describe("relativeChange", () => {
  it("returns a fraction and omits (null) on a non-positive or missing base", () => {
    expect(relativeChange(0.66, 0.6)).toBeCloseTo(0.1, 6);
    expect(relativeChange(0.6, 0)).toBeNull();
    expect(relativeChange(0.6, -0.1)).toBeNull();
    expect(relativeChange(null, 0.6)).toBeNull();
  });
});

describe("pointChange / formatPp", () => {
  it("subtracts fractions and tolerates a non-positive prior", () => {
    expect(pointChange(0.292, 0.302)).toBeCloseTo(-0.01, 6);
    expect(pointChange(0.05, -0.02)).toBeCloseTo(0.07, 6);
    expect(pointChange(null, 0.3)).toBeNull();
  });
  it("renders a signed pp string", () => {
    expect(formatPp(-0.01)).toBe("-1.0pp");
    expect(formatPp(0.011)).toBe("+1.1pp");
    expect(formatPp(null)).toBe(EM_DASH);
  });
});

describe("formatUsdCompact", () => {
  it("drops the trailing .0 for round magnitudes", () => {
    expect(formatUsdCompact(6e11)).toBe("$600B");
    expect(formatUsdCompact(1.305e11)).toBe("$130.5B");
    expect(formatUsdCompact(-2.4e9)).toBe("-$2.4B");
    expect(formatUsdCompact(null)).toBe(EM_DASH);
  });
});

describe("formatFyBadge", () => {
  it("is 2-digit so it never clips", () => {
    expect(formatFyBadge(2025)).toBe("FY25");
    expect(formatFyBadge(2007)).toBe("FY07");
    expect(formatFyBadge(null)).toBe(EM_DASH);
  });
});

describe("formatDayMonthYear", () => {
  it("is day-first, UTC-pinned, and always 3-letter months (Sep, never Sept)", () => {
    expect(formatDayMonthYear("2025-09-27")).toBe("27 Sep 2025");
    expect(formatDayMonthYear("2025-06-30")).toBe("30 Jun 2025");
    expect(formatDayMonthYear("2026-01-25")).toBe("25 Jan 2026");
    expect(formatDayMonthYear(null)).toBe(EM_DASH);
  });
});

describe("formatPerShare / formatShares", () => {
  it("per-share keeps cents (not adaptive)", () => {
    expect(formatPerShare(1.19)).toBe("$1.19");
    expect(formatPerShare(130.5)).toBe("$130.50");
  });
  it("share counts scale without a currency symbol", () => {
    expect(formatShares(2.4514e10)).toBe("24.5B");
    expect(formatShares(-1.2e6)).toBe("-1.2M");
  });
});

describe("formatMetric unit dispatch", () => {
  it("routes each unit and renders null as an em dash", () => {
    expect(formatMetric(mv({ value: 1.305e11, unit: "USD" }))).toBe("$130.5B");
    expect(formatMetric(mv({ value: 1.19, unit: "USD/shares" }))).toBe("$1.19");
    expect(formatMetric(mv({ value: 2.4514e10, unit: "shares" }))).toBe(
      "24.5B",
    );
    expect(formatMetric(mv({ value: 0.624, unit: "percent" }))).toBe("62.4%");
    expect(formatMetric(mv({ value: 54.31, unit: "ratio" }))).toBe("54.3x");
    expect(formatMetric(mv({ value: null, unit: "USD" }))).toBe(EM_DASH);
  });
});

describe("describeMetric", () => {
  it("present + clean -> value, no tooltip, not restated/missing", () => {
    const d = describeMetric(mv({ value: 1.305e11, unit: "USD" }));
    expect(d).toEqual({
      text: "$130.5B",
      tooltip: null,
      restated: false,
      missing: false,
    });
  });
  it("null + reason -> n.m. with the reason as tooltip (and not restated)", () => {
    const d = describeMetric(
      mv({ value: null, unit: "ratio", reason: "n.m. — negative EPS" }),
    );
    expect(d).toEqual({
      text: "n.m.",
      tooltip: "n.m. — negative EPS",
      restated: false,
      missing: true,
    });
  });
  it("null + no reason -> bare gap with the generic (overridable) tooltip", () => {
    const d = describeMetric(
      mv({ value: null, unit: "USD" }),
      "Free cash flow unavailable.",
    );
    expect(d.text).toBe(EM_DASH);
    expect(d.tooltip).toBe("Free cash flow unavailable.");
    expect(d.missing).toBe(true);
  });
  it("present + superseded -> value with a restatement tooltip", () => {
    const d = describeMetric(
      mv({
        value: 2.0e9,
        unit: "USD",
        superseded_value: 1.8e9,
        superseded_filed: "2024-10-31",
      }),
    );
    expect(d.text).toBe("$2.0B");
    expect(d.restated).toBe(true);
    expect(d.tooltip).toContain("Restated — originally $1.8B");
    expect(d.tooltip).toContain("31 Oct 2024");
  });
});
