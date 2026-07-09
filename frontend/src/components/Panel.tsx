import { Info } from "lucide-react";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** The skill's card header: 12px uppercase tracking-wide text-2 + optional info "i". */
export function Panel({
  title,
  info,
  actions,
  className,
  bodyClassName,
  children,
}: {
  title: string;
  info?: string;
  /** Right-aligned header controls (e.g. a range selector). */
  actions?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("flex h-full flex-col p-4", className)}>
      <div className="mb-3 flex min-h-6 items-center gap-1.5">
        <h2 className="text-xs uppercase tracking-wide text-fg-2">{title}</h2>
        {info && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`About ${title}`}
                className="focus-ring rounded text-fg-3 hover:text-fg-2"
              >
                <Info className="size-3.5" aria-hidden />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{info}</TooltipContent>
          </Tooltip>
        )}
        {actions && <div className="ml-auto">{actions}</div>}
      </div>
      <div className={cn("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </Card>
  );
}
