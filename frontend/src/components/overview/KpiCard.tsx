import type { MetricValue } from "@/api/contracts";
import { DeltaChip } from "@/components/metric/DeltaChip";
import { MetricText } from "@/components/metric/MetricText";
import { Card } from "@/components/ui/card";
import type { Polarity } from "@/lib/metrics";

export interface KpiSpec {
  label: string;
  value: MetricValue;
  /** Signed YoY delta; a fraction when deltaUnit is "pct", a point difference when "pp". Null omits. */
  delta: number | null;
  deltaReason?: string | null;
  /** Colours the chip by goodness of the change (defaults up-good). */
  polarity?: Polarity;
  /** "pp" for margins (point delta), "pct" otherwise. */
  deltaUnit?: "pct" | "pp";
  /** Overrides the generic tooltip when the value is a bare data gap. */
  missingFallback?: string;
}

/** label -> value (24/600) -> YoY delta chip, per the skill's KPI anatomy. The FY is carried by the
 *  top-bar chip, so the per-card FY sublabel is intentionally omitted. */
export function KpiCard({
  label,
  value,
  delta,
  deltaReason,
  polarity,
  deltaUnit,
  missingFallback,
}: KpiSpec) {
  return (
    <Card className="flex flex-col gap-2 p-4">
      <span className="text-xs uppercase tracking-wide text-fg-2">{label}</span>
      <MetricText
        mv={value}
        className="text-2xl font-semibold text-fg-1"
        missingFallback={missingFallback}
      />
      {/* Reserve the row height so cards with an omitted chip stay aligned. */}
      <div className="flex min-h-[22px] items-center">
        <DeltaChip
          fraction={delta}
          reason={deltaReason}
          polarity={polarity}
          unit={deltaUnit}
        />
      </div>
    </Card>
  );
}
