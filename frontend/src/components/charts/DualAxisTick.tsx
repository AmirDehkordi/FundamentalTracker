import { CHART } from "@/components/charts/chartTheme";

export interface SubLabel {
  text: string;
  muted?: boolean;
}

interface TickProps {
  x?: number;
  y?: number;
  payload?: { value?: string };
}

/**
 * A two-line category tick: the FY on top and a per-FY sub-value (FCF conversion / operating leverage)
 * beneath it. Returns a Recharts-compatible tick renderer closed over the sub-label map.
 */
export function makeFyTick(sub: Record<string, SubLabel | undefined>) {
  return function FyTick({ x = 0, y = 0, payload }: TickProps) {
    const fy = payload?.value ?? "";
    const s = sub[fy];
    return (
      <g transform={`translate(${x},${y})`}>
        <text textAnchor="middle">
          <tspan x={0} dy="0.95em" fontSize={12} fill={CHART.axis}>
            {fy}
          </tspan>
          {s && (
            <tspan
              x={0}
              dy="1.2em"
              fontSize={12}
              fill={s.muted ? CHART.text3 : CHART.text2}
            >
              {s.text}
            </tspan>
          )}
        </text>
      </g>
    );
  };
}
