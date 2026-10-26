import { useState } from "react";

import { ComparePanel } from "@/components/compare/ComparePanel";
import { MetricSelect } from "@/components/compare/MetricSelect";
import { DEFAULT_COMPARE_METRIC } from "@/lib/metrics";

/** Cross-company comparison: pick a metric, compare across the universe on each company's own latest FY. */
export function CompareTab() {
  const [metric, setMetric] = useState(DEFAULT_COMPARE_METRIC);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-fg-3">
          Metric
        </span>
        <MetricSelect value={metric} onChange={setMetric} />
      </div>
      <ComparePanel metric={metric} />
    </div>
  );
}
