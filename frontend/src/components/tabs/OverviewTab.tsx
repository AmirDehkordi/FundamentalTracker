import { CapexIntensityCard } from "@/components/overview/CapexIntensityCard";
import { EarningsQualityCard } from "@/components/overview/EarningsQualityCard";
import { FundamentalsPanel } from "@/components/overview/FundamentalsPanel";
import { InsiderCard } from "@/components/overview/InsiderCard";
import { KpiRow } from "@/components/overview/KpiRow";
import { PriceChartPanel } from "@/components/overview/PriceChartPanel";
import { RiskDiffCard } from "@/components/overview/RiskDiffCard";

/**
 * Reading order = importance: headline KPIs first, then two balanced columns so neither trails the
 * other into a void at >=1280px. Left (7/12): the fundamentals table, then the two analytical charts.
 * Right (5/12): the price trend, then the risk-factor and insider cards stacked beneath it.
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
            <CapexIntensityCard />
          </div>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-5">
          <PriceChartPanel />
          <RiskDiffCard />
          <InsiderCard />
        </div>
      </div>
    </div>
  );
}
