// Recharts reads colours from props, and CSS var() is unreliable inside SVG presentation attributes,
// so the design tokens are mirrored here as raw hex. Keep in lockstep with src/index.css.
export const CHART = {
  grid: "#2A2E34", // --border
  axis: "#868D96", // --text-3
  tooltipBg: "#1B1E22", // --surface-2
  tooltipBorder: "#2A2E34", // --border
  accent: "#E0A64E", // --accent (amber/gold)
  pos: "#45C88A", // --pos
  neg: "#E5736B", // --neg
  warn: "#D98E3C", // --warn
  text1: "#ECEDEF",
  text2: "#A8ADB5",
  text3: "#868D96",
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
