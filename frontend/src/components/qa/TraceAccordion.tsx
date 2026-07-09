import type { ToolTrace } from "@/api/contracts";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { friendlyTool } from "@/components/qa/labels";

function argChips(args: Record<string, unknown>) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="max-w-[12rem] truncate rounded bg-surface-2 px-1.5 py-0.5 text-xs tabular-nums text-fg-3"
        >
          {k}: {typeof v === "object" ? JSON.stringify(v) : String(v)}
        </span>
      ))}
    </div>
  );
}

/** The collapsed audit trail: one row per tool call (name, args, result summary). */
export function TraceAccordion({ trace }: { trace: ToolTrace[] }) {
  if (trace.length === 0) return null;
  const label = `How I answered · ${trace.length} ${trace.length === 1 ? "tool" : "tools"}`;
  return (
    <Accordion type="single" collapsible className="mt-2">
      <AccordionItem value="trace" className="border-border">
        <AccordionTrigger className="py-1.5 text-xs font-medium text-fg-2">
          {label}
        </AccordionTrigger>
        <AccordionContent className="pb-2">
          <ol className="space-y-2">
            {trace.map((t, i) => (
              <li key={i} className="text-13">
                <div className="flex items-baseline gap-2">
                  <span className="tabular-nums text-fg-3">{i + 1}</span>
                  <span className="text-fg-1">{friendlyTool(t.tool)}</span>
                  <span className="font-mono text-xs text-fg-3">{t.tool}</span>
                </div>
                {argChips(t.args)}
                <p className="mt-1 text-xs text-fg-3">{t.result_summary}</p>
              </li>
            ))}
          </ol>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
