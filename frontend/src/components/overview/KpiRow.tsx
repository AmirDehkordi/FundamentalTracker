import type { FundamentalsOut, FundamentalsRow } from "@/api/contracts";
import { useFundamentals } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { KpiCard, type KpiSpec } from "@/components/overview/KpiCard";
import { EmptyState } from "@/components/states";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatFySublabel, relativeChange } from "@/lib/format";
import { metricAt } from "@/lib/metrics";
import { useSelection } from "@/state/selection";

const ROW_CLASS = "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5";

const FCF_GAP =
  "Free cash flow unavailable: capital expenditure not reported for this fiscal year.";

/** Relative-% margin delta vs the prior consecutive FY; null (omit) otherwise. */
function marginDelta(
  latest: FundamentalsRow,
  prior: FundamentalsRow | undefined,
  key: string,
): number | null {
  if (!prior || prior.fiscal_year !== latest.fiscal_year - 1) return null;
  return relativeChange(
    metricAt(latest.metrics, key).value,
    metricAt(prior.metrics, key).value,
  );
}

function buildSpecs(data: FundamentalsOut): KpiSpec[] {
  const latest = data.rows[data.rows.length - 1];
  const prior = data.rows[data.rows.length - 2];
  const fyLabel = formatFySublabel(latest.fiscal_year, latest.period_end);

  const revYoy = metricAt(latest.yoy, "revenue");
  const niYoy = metricAt(latest.yoy, "net_income");

  return [
    {
      label: "Revenue",
      value: metricAt(latest.metrics, "revenue"),
      delta: revYoy.value,
      deltaReason: revYoy.reason,
      fyLabel,
    },
    {
      label: "Net income",
      value: metricAt(latest.metrics, "net_income"),
      delta: niYoy.value,
      deltaReason: niYoy.reason,
      fyLabel,
    },
    {
      label: "Gross margin",
      value: metricAt(latest.metrics, "gross_margin"),
      delta: marginDelta(latest, prior, "gross_margin"),
      fyLabel,
    },
    {
      label: "Operating margin",
      value: metricAt(latest.metrics, "operating_margin"),
      delta: marginDelta(latest, prior, "operating_margin"),
      fyLabel,
    },
    {
      label: "FCF margin",
      value: metricAt(latest.metrics, "fcf_margin"),
      delta: marginDelta(latest, prior, "fcf_margin"),
      fyLabel,
      missingFallback: FCF_GAP,
    },
  ];
}

function KpiSkeleton() {
  return (
    <div className={ROW_CLASS}>
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i} className="p-4">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-3 h-6 w-24" />
          {/* Reserve the delta-chip row so the card doesn't grow (and shift the page) on load. */}
          <Skeleton className="mt-3 h-[22px] w-16 rounded" />
          <Skeleton className="mt-3 h-3 w-20" />
        </Card>
      ))}
    </div>
  );
}

/** The five headline KPIs for the latest reported FY. Revenue/Net income use backend YoY; the three
 *  margins use a client-computed relative-% change vs the prior consecutive FY. */
export function KpiRow() {
  const { ticker } = useSelection();
  const query = useFundamentals(ticker);

  return (
    <AsyncBoundary
      query={query}
      skeleton={<KpiSkeleton />}
      errorTitle="Couldn't load fundamentals"
      isEmpty={(d) => d.rows.length === 0}
      empty={<EmptyState>No fundamentals reported yet.</EmptyState>}
    >
      {(data) => (
        <div className={ROW_CLASS}>
          {buildSpecs(data).map((spec) => (
            <KpiCard key={spec.label} {...spec} />
          ))}
        </div>
      )}
    </AsyncBoundary>
  );
}
