import { TriangleAlert } from "lucide-react";

import type { FinalAnswer } from "@/api/contracts";
import { CitationPills } from "@/components/qa/CitationPills";
import { Markdown } from "@/components/qa/markdown";
import { TraceAccordion } from "@/components/qa/TraceAccordion";

/**
 * An answer turn. A declined answer gets a warn-tinted card (distinct from a transport error, which
 * is un-tinted and offers Retry). Citations and trace still render on a decline — an out-of-universe
 * question can still have consulted `list_universe`.
 */
export function AssistantMessage({ answer }: { answer: FinalAnswer }) {
  if (answer.declined) {
    const reason = answer.decline_reason?.trim();
    const body = answer.answer_md.trim();
    // Prefer the model's markdown sentence; fall back to the reason if the body is thin (some infra
    // declines carry only a reason). Body text stays neutral — never amber-on-amber.
    const shown =
      body || reason || "This can't be answered from the tracked data.";
    return (
      <div
        className="rounded-md border p-3"
        style={{
          backgroundColor: "rgba(251,191,36,0.10)",
          borderColor: "rgba(251,191,36,0.35)",
        }}
      >
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-warn">
          <TriangleAlert className="size-3.5" aria-hidden />
          Declined
        </div>
        <Markdown>{shown}</Markdown>
        {reason && body && <p className="mt-1.5 text-xs text-fg-3">{reason}</p>}
        <CitationPills citations={answer.citations} />
        <TraceAccordion trace={answer.trace} />
      </div>
    );
  }

  return (
    <div>
      <Markdown>{answer.answer_md}</Markdown>
      <CitationPills citations={answer.citations} />
      <TraceAccordion trace={answer.trace} />
    </div>
  );
}
