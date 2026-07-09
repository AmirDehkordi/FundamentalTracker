import { EarningsQualityCard } from "@/components/overview/EarningsQualityCard";
import { FundamentalsPanel } from "@/components/overview/FundamentalsPanel";
import { IncrementalOperatingMarginCard } from "@/components/overview/IncrementalOperatingMarginCard";
import { InsiderCard } from "@/components/overview/InsiderCard";
import { KpiRow } from "@/components/overview/KpiRow";
import { PriceChartPanel } from "@/components/overview/PriceChartPanel";
import { RiskDiffCard } from "@/components/overview/RiskDiffCard";

/**
 * Reading order = importance: headline KPIs first, then two balanced columns so neither trails the
 * other into a void at >=1280px. Left (7/12): the fundamentals table, then the two analytical charts.
 * Right (5/12): the price trend, then insider and risk-factor cards stacked beneath it.
 */
export function OverviewTab() {
  return (
    <div className="space-y-4">
      <KpiRow />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="flex flex-col gap-4 lg:col-span-7">
          <FundamentalsPanel />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <EarningsQualityCard />
            <IncrementalOperatingMarginCard />
          </div>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-5">
          <PriceChartPanel />
          <InsiderCard />
          <RiskDiffCard />
        </div>
      </div>
    </div>
  );
}
