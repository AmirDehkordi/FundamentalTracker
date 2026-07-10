import { MessageCircleQuestion, TriangleAlert } from "lucide-react";

import type { FinalAnswer } from "@/api/contracts";
import { CitationPills } from "@/components/qa/CitationPills";
import { Markdown } from "@/components/qa/markdown";
import { TraceAccordion } from "@/components/qa/TraceAccordion";
import { useConversation } from "@/state/conversation";

/** Suggested follow-up prompts as clickable chips; clicking asks that question. Renders nothing when
 * the list is empty. */
function Followups({ items }: { items: string[] }) {
  const { send, isThinking } = useConversation();
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {items.map((q, i) => (
        <button
          key={`${i}-${q}`}
          type="button"
          disabled={isThinking}
          onClick={() => send(q)}
          className="rounded-full border border-border px-2.5 py-1 text-xs text-fg-2 transition-colors hover:border-brand hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          {q}
        </button>
      ))}
    </div>
  );
}

/**
 * An answer turn, styled by `kind`:
 *  - clarification: a neutral "one question back" card + suggested rephrasings (NOT a refusal).
 *  - decline / error: a warn-tinted card (distinct from a transport error, which offers Retry) + any
 *    in-scope follow-ups.
 *  - answer: plain markdown.
 * Citations and trace still render on a decline — an out-of-universe question can still have consulted
 * `list_universe`.
 */
export function AssistantMessage({ answer }: { answer: FinalAnswer }) {
  const followups = answer.suggested_followups ?? [];

  if (answer.kind === "clarification") {
    return (
      <div className="rounded-md border border-border p-3">
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-brand">
          <MessageCircleQuestion className="size-3.5" aria-hidden />
          One quick question
        </div>
        <Markdown>{answer.answer_md}</Markdown>
        <Followups items={followups} />
        <TraceAccordion trace={answer.trace} />
      </div>
    );
  }

  if (answer.declined) {
    const reason = answer.decline_reason?.trim();
    const body = answer.answer_md.trim();
    // Prefer the model's markdown sentence; fall back to the reason if the body is thin (some infra
    // declines carry only a reason). Body text stays neutral — never amber-on-amber.
    const shown =
      body || reason || "This can't be answered from the tracked data.";
    const label = answer.kind === "error" ? "Something went wrong" : "Declined";
    return (
      <div
        className="rounded-md border p-3"
        style={{
          backgroundColor: "rgba(217,142,60,0.10)",
          borderColor: "rgba(217,142,60,0.35)",
        }}
      >
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-warn">
          <TriangleAlert className="size-3.5" aria-hidden />
          {label}
        </div>
        <Markdown>{shown}</Markdown>
        {reason && body && <p className="mt-1.5 text-xs text-fg-3">{reason}</p>}
        <Followups items={followups} />
        <CitationPills citations={answer.citations} />
        <TraceAccordion trace={answer.trace} />
      </div>
    );
  }

  return (
    <div>
      <Markdown>{answer.answer_md}</Markdown>
      <Followups items={followups} />
      <CitationPills citations={answer.citations} />
      <TraceAccordion trace={answer.trace} />
    </div>
  );
}
