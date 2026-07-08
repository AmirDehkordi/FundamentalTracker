import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Error: one sentence + a Retry button (disabled while a retry is in flight). */
export function ErrorState({
  title,
  onRetry,
  busy,
  className,
}: {
  title: string;
  onRetry: () => void;
  busy?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-start gap-2", className)}>
      <p className="text-13 text-fg-2">{title}.</p>
      <Button
        variant="outline"
        size="sm"
        onClick={onRetry}
        disabled={busy}
        className="focus-visible:ring-2"
      >
        <RefreshCw
          className={cn("size-3.5", busy && "animate-spin")}
          aria-hidden
        />
        Retry
      </Button>
    </div>
  );
}

/** Not-ready: a calm caption for a stub endpoint (501) — deliberately not styled as an error. */
export function NotReady({
  label = "Not available yet",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return <span className={cn("text-13 text-fg-3", className)}>{label}</span>;
}

/** Empty: one plain sentence stating the fact and what would fill the panel. */
export function EmptyState({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <p className={cn("text-13 text-fg-2", className)}>{children}</p>;
}
