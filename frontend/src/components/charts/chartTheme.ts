// Recharts reads colours from props, and CSS var() is unreliable inside SVG presentation attributes,
// so the design tokens are mirrored here as raw hex. Keep in lockstep with src/index.css.
export const CHART = {
  grid: "#232C37", // --border
  axis: "#7B8794", // --text-3
  tooltipBg: "#171E27", // --surface-2
  tooltipBorder: "#232C37", // --border
  accent: "#6EA8FE", // --accent
  pos: "#34D399", // --pos
  neg: "#F87171", // --neg
  warn: "#FBBF24", // --warn
  text1: "#E7ECF3",
  text2: "#A9B4C2",
  text3: "#7B8794",
} as const;

// Horizontal-only dashed gridlines (skill: "Grid: horizontal only, --border, dashed 3-3").
export const gridProps = {
  stroke: CHART.grid,
  strokeDasharray: "3 3",
  vertical: false,
} as const;

// Axes: 12px text-3, no axis lines (skill).
export const axisBase = {
  stroke: CHART.grid,
  axisLine: false,
  tickLine: false,
  tick: { fill: CHART.axis, fontSize: 12 },
} as const;

export const CHART_MARGIN = { top: 8, right: 12, bottom: 4, left: 4 } as const;
