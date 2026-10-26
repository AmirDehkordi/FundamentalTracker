import { describe, expect, it } from "vitest";

import { polarityOf, toneForDelta } from "@/lib/metrics";

describe("polarityOf", () => {
  it("flags rising costs and dilution as up-bad, capex as neutral, defaults up-good", () => {
    expect(polarityOf("cost_of_revenue")).toBe("up-bad");
    expect(polarityOf("shares_diluted")).toBe("up-bad");
    expect(polarityOf("capex")).toBe("neutral");
    expect(polarityOf("revenue")).toBe("up-good");
    expect(polarityOf("something_unmapped")).toBe("up-good");
  });
});

describe("toneForDelta", () => {
  it("colours by goodness, not raw sign", () => {
    expect(toneForDelta(0.1, "up-good")).toBe("pos");
    expect(toneForDelta(-0.1, "up-good")).toBe("neg");
    // a cost falling is good (green) even though it points down
    expect(toneForDelta(-0.1, "up-bad")).toBe("pos");
    expect(toneForDelta(0.1, "up-bad")).toBe("neg");
  });
  it("zero and neutral-polarity are always grey", () => {
    expect(toneForDelta(0, "up-good")).toBe("neutral");
    expect(toneForDelta(0.1, "neutral")).toBe("neutral");
  });
});
