import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

// Tint backgrounds need alpha over the token hue; Tailwind can't add alpha to a var()-valued colour,
// so the tint is an inline rgba while the text colour stays a token class.
const TONE = {
  pos: { text: "text-pos", bg: "rgba(52,211,153,0.14)" },
  neg: { text: "text-neg", bg: "rgba(248,113,113,0.14)" },
  neutral: { text: "text-fg-2", bg: "rgba(123,135,148,0.14)" },
} as const;

const chipClass =
  "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-medium tabular-nums";

/**
 * A YoY delta as arrow + signed % on a pos/neg tint (never colour alone). `fraction` is a signed
 * fraction (0.114 -> +11.4%). null with a `reason` renders a muted "n.m." chip; null without a reason
 * renders nothing (the caller omits the delta).
 */
export function DeltaChip({
  fraction,
  reason,
  className,
}: {
  fraction: number | null | undefined;
  reason?: string | null;
  className?: string;
}) {
  if (fraction == null || !Number.isFinite(fraction)) {
    if (!reason) return null;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              chipClass,
              TONE.neutral.text,
              "cursor-help",
              className,
            )}
            style={{ backgroundColor: TONE.neutral.bg }}
          >
            n.m.
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{reason}</TooltipContent>
      </Tooltip>
    );
  }

  const tone = fraction > 0 ? TONE.pos : fraction < 0 ? TONE.neg : TONE.neutral;
  const Arrow = fraction > 0 ? ArrowUp : fraction < 0 ? ArrowDown : ArrowRight;

  return (
    <span
      className={cn(chipClass, tone.text, className)}
      style={{ backgroundColor: tone.bg }}
    >
      <Arrow className="size-3" aria-hidden />
      {formatSignedPercent(fraction)}
    </span>
  );
}
