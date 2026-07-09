import { EarningsQualityCard } from "@/components/overview/EarningsQualityCard";
import { FundamentalsPanel } from "@/components/overview/FundamentalsPanel";
import { InsiderCard } from "@/components/overview/InsiderCard";
import { KpiRow } from "@/components/overview/KpiRow";
import { OperatingLeverageCard } from "@/components/overview/OperatingLeverageCard";
import { PriceChartPanel } from "@/components/overview/PriceChartPanel";
import { RiskDiffCard } from "@/components/overview/RiskDiffCard";

/** Reading order = importance: headline KPIs -> detail table + price trend -> analytical cards. */
export function OverviewTab() {
  return (
    <div className="space-y-4">
      <KpiRow />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <FundamentalsPanel />
        </div>
        <div className="lg:col-span-5">
          <PriceChartPanel />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <EarningsQualityCard />
        <OperatingLeverageCard />
        <InsiderCard />
        <RiskDiffCard />
      </div>
    </div>
  );
}
