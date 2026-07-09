import { useEffect, useRef } from "react";
import { SquarePen, X } from "lucide-react";

import { ChatInput } from "@/components/qa/ChatInput";
import { ExampleChips } from "@/components/qa/ExampleChips";
import { ExchangeList } from "@/components/qa/ExchangeList";
import { ThinkingRow } from "@/components/qa/ThinkingRow";
import { UserMessage } from "@/components/qa/UserMessage";
import { ErrorState } from "@/components/states";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useConversation } from "@/state/conversation";

/**
 * The Q&A slide-over. Conversation state and the ask mutation live in ConversationProvider (above
 * the Sheet), so a request survives closing the panel; here we only render the thread, the pending
 * question, the thinking/error rows, and the input, keeping long answers scrolling inside the Sheet.
 */
export function QAPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { exchanges, pending, isThinking, isError, send, retry, reset } =
    useConversation();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    bottomRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  }, [exchanges.length, isThinking, isError]);

  const empty = exchanges.length === 0 && pending === null;

  const canReset = (exchanges.length > 0 || pending !== null) && !isThinking;

  return (
    // Non-modal + no overlay: the dashboard stays readable and interactive while the panel is open;
    // clicking the dashboard must not close it, so interactions outside are ignored.
    <Sheet open={open} onOpenChange={onOpenChange} modal={false}>
      <SheetContent
        side="right"
        overlay={false}
        hideClose
        onInteractOutside={(e) => e.preventDefault()}
        className="w-full border-border bg-surface-1 p-0 shadow-2xl sm:max-w-[400px]"
      >
        <div className="flex h-full flex-col">
          <SheetHeader className="space-y-1 border-b border-border p-4 text-left">
            <div className="flex items-center justify-between gap-2">
              <SheetTitle className="text-sm font-semibold text-fg-1">
                SchonAI
              </SheetTitle>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={reset}
                  disabled={!canReset}
                  className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                >
                  <SquarePen className="size-3.5" aria-hidden />
                  New Chat
                </button>
                <SheetClose
                  className="focus-ring inline-flex size-7 items-center justify-center rounded-md text-fg-2 hover:bg-surface-2"
                  aria-label="Close"
                >
                  <X className="size-4" aria-hidden />
                </SheetClose>
              </div>
            </div>
            {/* Kept for screen readers (Radix needs a description) but hidden — the placeholder and the
                example chips already tell a sighted user what to ask. */}
            <SheetDescription className="sr-only">
              Ask about fundamentals, filings, prices, or insider activity.
              Answers cite their sources.
            </SheetDescription>
          </SheetHeader>

          <div className="min-h-0 flex-1">
            <ScrollArea className="h-full">
              <div className="flex flex-col gap-4 p-4">
                {empty ? (
                  <div className="flex flex-col gap-3">
                    <p className="text-13 text-fg-2">
                      Try one of these, or ask your own.
                    </p>
                    <ExampleChips onPick={send} disabled={isThinking} />
                  </div>
                ) : (
                  // Every user turn renders as a bubble (settled ones here; the in-flight one below).
                  // Assistant turns render by kind (answer / clarification / declined / error) with
                  // follow-up chips when provided — see AssistantMessage. Transport errors show a Retry
                  // row below; if the backend omits kind/suggested_followups, AssistantMessage defaults
                  // to a plain answer with no chips.
                  <ExchangeList exchanges={exchanges} />
                )}
                {pending !== null && <UserMessage text={pending} />}
                {isThinking && <ThinkingRow />}
                {isError && (
                  <ErrorState
                    title="Couldn't reach the assistant"
                    onRetry={retry}
                    busy={isThinking}
                  />
                )}
                <div ref={bottomRef} />
              </div>
            </ScrollArea>
          </div>

          <div className="border-t border-border p-3">
            <ChatInput
              onSend={send}
              disabled={isThinking}
              loading={isThinking}
            />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
