export interface LegendItemDef {
  label: string;
  color: string;
}

/** A centered swatch+label legend row beneath a chart (skill: charts label their series explicitly). */
export function ChartLegend({ items }: { items: LegendItemDef[] }) {
  return (
    <div className="mt-2 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
      {items.map((it) => (
        <span
          key={it.label}
          className="flex items-center gap-1.5 text-xs text-fg-3"
        >
          <span
            className="size-2 shrink-0 rounded-[2px]"
            style={{ background: it.color }}
            aria-hidden
          />
          {it.label}
        </span>
      ))}
    </div>
  );
}
