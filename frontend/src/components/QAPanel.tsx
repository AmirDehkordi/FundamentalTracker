import { useEffect, useRef } from "react";

import { ChatInput } from "@/components/qa/ChatInput";
import { ExampleChips } from "@/components/qa/ExampleChips";
import { ExchangeList } from "@/components/qa/ExchangeList";
import { ThinkingRow } from "@/components/qa/ThinkingRow";
import { UserMessage } from "@/components/qa/UserMessage";
import { ErrorState } from "@/components/states";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
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
  const { exchanges, pending, isThinking, isError, send, retry } =
    useConversation();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    bottomRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  }, [exchanges.length, isThinking, isError]);

  const empty = exchanges.length === 0 && pending === null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full border-border bg-surface-1 p-0 sm:max-w-[400px]"
      >
        <div className="flex h-full flex-col">
          <SheetHeader className="space-y-1 border-b border-border p-4 text-left">
            <SheetTitle className="text-sm font-semibold text-fg-1">
              Ask
            </SheetTitle>
            <SheetDescription className="text-13 text-fg-3">
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
            <ChatInput onSend={send} disabled={isThinking} />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
