import { cn } from "@/lib/utils";

// Data spans ~2y, so a dedicated "2Y" would be identical to MAX — dropped to avoid a redundant option.
export const PRICE_RANGES = [
  { key: "1m", label: "1M" },
  { key: "6m", label: "6M" },
  { key: "1y", label: "1Y" },
  { key: "max", label: "MAX" },
] as const;

export type RangeKey = (typeof PRICE_RANGES)[number]["key"];

/** Segmented control for the price window. MAX renders the full ~2y of stored history. */
export function RangeSelector({
  value,
  onChange,
}: {
  value: RangeKey;
  onChange: (key: RangeKey) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Price range"
      className="inline-flex items-center gap-0.5 rounded-md border border-border p-0.5"
    >
      {PRICE_RANGES.map((r) => {
        const active = r.key === value;
        return (
          <button
            key={r.key}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(r.key)}
            className={cn(
              "focus-ring rounded px-2 py-0.5 text-xs font-medium tabular-nums transition-colors",
              active ? "bg-accent-bg text-fg-1" : "text-fg-3 hover:text-fg-2",
            )}
          >
            {r.label}
          </button>
        );
      })}
    </div>
  );
}
