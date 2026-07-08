import { useState } from "react";

import { QAPanel } from "@/components/QAPanel";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { CompareTab } from "@/components/tabs/CompareTab";
import { OverviewTab } from "@/components/tabs/OverviewTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function App() {
  const [askOpen, setAskOpen] = useState(false);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-bg text-fg-1">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onAskClick={() => setAskOpen(true)} />
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-[1440px] p-4">
            <Tabs defaultValue="overview">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="compare">Compare</TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="mt-4">
                <OverviewTab />
              </TabsContent>
              <TabsContent value="compare" className="mt-4">
                <CompareTab />
              </TabsContent>
            </Tabs>
          </div>
        </main>
      </div>
      <QAPanel open={askOpen} onOpenChange={setAskOpen} />
    </div>
  );
}
