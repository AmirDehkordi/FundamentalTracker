import type { MetricValue } from "@/api/contracts";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { describeMetric, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Renders one MetricValue: formatted value, or "n.m."/em dash for a null, with a tooltip carrying the
 * reason (n.m.), a restatement note, or a generic gap message. A restated value gets a small dagger.
 * `missingFallback` overrides the generic tooltip for a bare data gap (e.g. an FCF-specific reason).
 * `signed` forces a leading + on a positive percent value — the percent unit is unsigned by default, so
 * YoY/growth callers (e.g. the Compare tab's revenue_yoy) opt into signing here.
 */
export function MetricText({
  mv,
  className,
  missingFallback,
  signed,
}: {
  mv: MetricValue;
  className?: string;
  missingFallback?: string;
  signed?: boolean;
}) {
  const d = describeMetric(mv, missingFallback);
  const text =
    signed && mv.unit === "percent" && mv.value != null
      ? formatSignedPercent(mv.value)
      : d.text;
  const body = (
    <span className={cn("tabular-nums", d.missing && "text-fg-3", className)}>
      {text}
      {d.restated && (
        <sup className="ml-0.5 text-fg-3" aria-label="restated">
          †
        </sup>
      )}
    </span>
  );

  if (!d.tooltip) return body;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help underline decoration-fg-3 decoration-dotted underline-offset-2">
          {body}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{d.tooltip}</TooltipContent>
    </Tooltip>
  );
}
