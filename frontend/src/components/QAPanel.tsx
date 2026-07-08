import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The Q&A slide-over. This chunk ships the shell only — open/close, header, and the empty state.
 * The thread, citations, and trace land in a later chunk.
 */
export function QAPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
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

          <div className="flex flex-1 flex-col items-center justify-center gap-1.5 p-6 text-center">
            <p className="text-13 text-fg-2">No questions yet.</p>
            <p className="text-xs text-fg-3">
              Try “What changed in NVDA's risk factors?” once Q&amp;A is live.
            </p>
          </div>

          <div className="border-t border-border p-4">
            <div className="flex items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-2">
              <Skeleton className="h-4 flex-1" />
            </div>
            <p className="mt-2 text-xs text-fg-3">
              Q&amp;A lands in a later chunk.
            </p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
