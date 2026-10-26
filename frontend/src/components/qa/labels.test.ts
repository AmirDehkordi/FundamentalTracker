import { describe, expect, it } from "vitest";

import type { Citation } from "@/api/contracts";
import { citationDetailHint, citationLabel } from "@/components/qa/labels";

const base: Citation = {
  source_type: "fundamental",
  ticker: "NVDA",
  fiscal_year: 2024,
  item: null,
  accession: "0001045810-26-000021",
  url: null,
  detail: "Revenue $60.922B, FY2024 (ended 2024-01-28)",
};

describe("citationLabel", () => {
  it("builds the ticker-first face with FY and accession tail", () => {
    expect(citationLabel(base)).toBe("NVDA · XBRL · FY2024 · accn …000021");
  });

  it("prefers the item over the accession for filing citations", () => {
    expect(citationLabel({ ...base, source_type: "filing", item: "1A" })).toBe(
      "NVDA · 10-K · FY2024 · Item 1A",
    );
  });
});

describe("citationDetailHint", () => {
  it("extracts the leading concept words before the first figure", () => {
    expect(citationDetailHint("Revenue $60.922B, FY2024")).toBe("Revenue");
    expect(citationDetailHint("Net income $29.760B, FY2024")).toBe(
      "Net income",
    );
    expect(citationDetailHint("Close $314.78 as of 2026-07-09")).toBe("Close");
  });

  it("returns null when nothing usable leads the detail", () => {
    expect(citationDetailHint(null)).toBeNull();
    expect(citationDetailHint("")).toBeNull();
    expect(citationDetailHint("$60.922B revenue")).toBeNull();
    expect(citationDetailHint("2024-01-28 close")).toBeNull();
  });
});
