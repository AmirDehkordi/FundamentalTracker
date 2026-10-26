/** Shared surface-2 tooltip shell for every chart, so content differs but the chrome stays identical. */
export interface TooltipRow {
  label?: string;
  value: string;
  /** Optional swatch matching the series colour. */
  color?: string;
}

export function TooltipShell({
  title,
  rows,
  note,
}: {
  title: string;
  rows: TooltipRow[];
  /** Optional muted footnote (e.g. an n.m. reason). */
  note?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs">
      <p className="mb-1 font-medium tabular-nums text-fg-2">{title}</p>
      <ul className="space-y-0.5">
        {rows.map((r, i) => (
          <li
            key={i}
            className="flex items-center gap-2 tabular-nums text-fg-1"
          >
            {r.color && (
              <span
                className="size-2 shrink-0 rounded-[2px]"
                style={{ background: r.color }}
                aria-hidden
              />
            )}
            {r.label && <span className="text-fg-3">{r.label}</span>}
            <span className="ml-auto pl-3 font-medium">{r.value}</span>
          </li>
        ))}
      </ul>
      {note && <p className="mt-1 max-w-[16rem] text-fg-3">{note}</p>}
    </div>
  );
}
