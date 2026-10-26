import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatPp, formatSignedPercent } from "@/lib/format";
import { type Polarity, toneForDelta } from "@/lib/metrics";
import { cn } from "@/lib/utils";

// Tint backgrounds need alpha over the token hue; Tailwind can't add alpha to a var()-valued colour,
// so the tint is an inline rgba while the text colour stays a token class. (Hues match src/index.css.)
const TONE = {
  pos: { text: "text-pos", bg: "rgba(69,200,138,0.14)" },
  neg: { text: "text-neg", bg: "rgba(229,115,107,0.14)" },
  neutral: { text: "text-fg-2", bg: "rgba(134,141,150,0.14)" },
} as const;

const chipClass =
  "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-medium tabular-nums";

/**
 * A YoY delta as arrow + signed value on a tint (never colour alone). `fraction` is a signed number:
 * a fraction (0.114 -> "+11.4%") for unit "pct", or a point difference (-0.010 -> "-1.0pp") for "pp".
 * ARROW reflects the direction of change; COLOUR reflects goodness via `polarity` (a cost falling is
 * green even though it points down). null with a `reason` renders a muted "n.m." chip; null without a
 * reason renders nothing (the caller omits the delta).
 */
export function DeltaChip({
  fraction,
  reason,
  polarity = "up-good",
  unit = "pct",
  className,
}: {
  fraction: number | null | undefined;
  reason?: string | null;
  polarity?: Polarity;
  unit?: "pct" | "pp";
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

  const tone = TONE[toneForDelta(fraction, polarity)];
  const Arrow = fraction > 0 ? ArrowUp : fraction < 0 ? ArrowDown : ArrowRight;

  return (
    <span
      className={cn(chipClass, tone.text, className)}
      style={{ backgroundColor: tone.bg }}
    >
      <Arrow className="size-3" aria-hidden />
      {unit === "pp" ? formatPp(fraction) : formatSignedPercent(fraction)}
    </span>
  );
}
