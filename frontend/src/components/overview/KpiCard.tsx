import type { MetricValue } from "@/api/contracts";
import { DeltaChip } from "@/components/metric/DeltaChip";
import { MetricText } from "@/components/metric/MetricText";
import { Card } from "@/components/ui/card";

export interface KpiSpec {
  label: string;
  value: MetricValue;
  /** Signed YoY delta as a fraction; null omits the chip (unless a reason is given). */
  delta: number | null;
  deltaReason?: string | null;
  fyLabel: string;
  /** Overrides the generic tooltip when the value is a bare data gap. */
  missingFallback?: string;
}

/** label -> value (24/600) -> YoY delta chip -> FY sublabel, per the skill's KPI anatomy. */
export function KpiCard({
  label,
  value,
  delta,
  deltaReason,
  fyLabel,
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
        <DeltaChip fraction={delta} reason={deltaReason} />
      </div>
      <span className="text-xs text-fg-3">{fyLabel}</span>
    </Card>
  );
}
