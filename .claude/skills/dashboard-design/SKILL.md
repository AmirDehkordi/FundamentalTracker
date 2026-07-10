---
name: dashboard-design
description: Design authority for the Fundamentals Tracker frontend. Use whenever creating or modifying any UI component, style, layout, chart, or state. Defines the dark theme tokens, contrast rules, layout map, typography, chart conventions, and interaction states.
---

# Dashboard design system — "graphite terminal"

Intent: an institutional analyst tool. Dense but calm; the data is the interface. Neutral graphite
surfaces, one warm accent (amber) spent sparingly. If a choice feels decorative, delete it. The user is a
PM/analyst deciding in seconds whether a number matters — hierarchy, alignment, and labels do the work.

## Tokens (implement as CSS variables; map into Tailwind theme)
All pairs below are WCAG-verified >= 4.5:1 (script in the frontend lane). Change any hex in FOUR places in
lockstep: src/index.css, tailwind.config.ts (colors.ticker), src/lib/tickers.ts, and
src/components/charts/chartTheme.ts.

Backgrounds (neutral graphite, never pure black, no blue tint):
  --bg          #0C0D0F   app background
  --surface-1   #131518   cards, sidebar
  --surface-2   #1B1E22   hover, table row hover, chart tooltip, inputs
  --border      #2A2E34   1px hairlines everywhere; no shadows for elevation
Text (off-white, never pure white, NEVER dark-on-dark):
  --text-1      #ECEDEF   primary — 15.6:1 on surface-1
  --text-2      #A8ADB5   secondary/labels — 8.1:1
  --text-3      #868D96   captions/hints only, min 12px — 5.5:1. Nothing dimmer than this, ever.
Accent (single, warm gold — desaturated so it doesn't vibrate on dark):
  --accent      #E0A64E   interactive: links, active tab, focus ring, primary button
  --accent-bg   #2A2212   selected states, chips
  PRIMARY BUTTON: foreground is --bg (dark) on the amber fill (9:1). NEVER --text-1 on accent (1.8:1).
Semantics (desaturated for dark):
  --pos #45C88A  --neg #E5736B  --warn #D98E3C   (deltas ALSO carry an arrow/sign — never colour alone)
Fixed per-ticker series colours (same everywhere: charts, compare, legends) — one muted family, none
colliding with a semantic or the accent (NVDA/MSFT/AAPL also echo the price chart):
  NVDA #6E9BF0 (blue) · MSFT #2DB6A6 (teal) · AAPL #A78BFA (violet) · GOOGL #CE7CA6 (rose) · ETN #D68A5A (terracotta)

HARD RULE — contrast: every text/background pair >= 4.5:1 (3:1 for >= 20px semibold). When adding ANY new
colour pairing, verify against the token list. Dark or black text on dark surfaces is a build-breaking bug.

## Typography and numbers
Inter (fallback system-ui). Sizes only: 12 caption · 13 table body · 14 UI body · 16 card values-small ·
20 section · 24 KPI value. Weights 400/500/600 only. ALL numeric cells: font-variant-numeric: tabular-nums,
right-aligned. Formats: percents 1dp ("62.4%"); percentage-POINT deltas ("-1.0pp", for margin YoY);
currency adaptive ("$130.5B", "$964M"); axis currency drops the trailing .0 ("$600B"); ratios 1dp ("54.3x");
undefined -> em dash + tooltip reason ("n.m. — negative EPS"). Every fiscal value is labelled
"FY2025 (ended 27 Sep 2025)" — the label is a feature, not clutter. Sidebar FY badge is 2-digit ("FY25").
Company names use display names (Microsoft, Apple, Alphabet, NVIDIA, Eaton), never raw EDGAR caps.

TWO-LINE HEADER RULE: a fiscal column header is at most two lines — the period on top, the ended-date below
in text-3 ("FY2025" over "ended 27 Sep 2025"). One date format app-wide: "ended 27 Sep 2025" (never "Sept").
Exception: the fundamentals table packs up to 4 FY columns + YoY into a 7/12 panel, where "ended " pushes
the nowrap sub-label past the column budget and forces horizontal scroll — there the sub-label shrinks to
11px (below the 12px caption floor, a deliberate one-off via an arbitrary Tailwind value, not a new scale
step) and abbreviates to "e." ("FY2025" over "e. 27 Sep 2025"); every wider spot (top-bar chip, tooltips)
keeps the full 12px "ended" phrasing.

POLARITY-MAP RULE: a delta's ARROW shows the direction of change; its COLOUR shows goodness via a per-metric
polarity (lib/metrics METRIC_POLARITY). Rising costs / rising diluted shares are red though they point up; a
falling cost is green though it points down; capex is neutral (grey). Zero and neutral-polarity are grey.

## Layout map (desktop-first, min 1280px; content max 1440px, 12-col grid, 16px gutters, 4px spacing base)
┌ sidebar 232px ┬ top bar 56px ──────────────────────────────┬ Q&A Sheet 400px (non-modal slide-over) ┐
│ logo+wordmark │ company name+ticker · FY chip · trailing   │ New chat · thread · input             │
│ 5 companies   │ P/E · freshness · [Ask]  (Compare tab ->   │ citations · trace accordion           │
│ (ticker bold, │  neutral "Universe · N companies" header)  │                                       │
│  name muted,  ├ Tabs: Overview | Compare ───────────────────┤                                       │
│  FY25 badge)  │ Overview: KPI row (5 cards)                 │                                       │
│               │ LEFT 7/12: fundamentals table, then         │                                       │
│               │   [earnings-quality | capex intensity]      │                                       │
│               │ RIGHT 5/12: price chart, then insider,      │                                       │
│               │   then risk-factors (stacked)               │                                       │
└──────────────┴─────────────────────────────────────────────┴───────────────────────────────────────┘
Reading order = importance: identity -> headline KPIs -> detail table/trend -> analytical cards. The two
columns are BALANCED vertical stacks so neither trails into a void at >=1280px. Freshness ("Prices as of…")
appears ONCE, in the top bar. Q&A is a NON-MODAL slide-over (no scrim) so the dashboard stays readable and
interactive while asking; it does not close on outside interaction.

## Components (shadcn/ui: Tabs, Card, Table, Badge, Button, Sheet, Select, Skeleton, Tooltip, Accordion,
ScrollArea, Separator)
Cards: surface-1, 1px border, radius 10, padding 16, header = 12px uppercase tracking-wide text-2 + optional
Tooltip "i". KPI card: label(12/text-2) -> value(24/600/text-1) -> delta chip(12: arrow+sign+value on
pos/neg/neutral tint, coloured by the polarity map; margins show "pp"). No per-card FY sublabel — the top-bar
FY chip carries it. Tables: header row 12px uppercase text-2, rows 38px, hover surface-2, first column
sticky, hairline row borders only. Sidebar item: 40px, active = accent-bg tint + 2px accent left bar. Focus:
2px accent ring, always visible, on every interactive element.

## Charts (Recharts)
Grid: horizontal only, --border, dashed 3-3. Axes: 12px text-3, no axis lines, round ticks. Tooltip:
surface-2, border, full precision + date. Every chart labels its series in a legend (charts/ChartLegend).
Price chart: 1.5px accent line + 8% area fill; dashed 150-day MA (text-2); a low-opacity volume sub-panel in
the bottom ~20% on a HIDDEN companion axis; a last-price callout dot+value; range segmented control
[6M 1Y 2Y]; 10-K dates = ReferenceLine (--border, dashed) +
tiny "10-K" label (text-3), nudged inward when near the y-axis. Compare: grouped/single bars, per-ticker
fixed colours, value labels 12px, each bar footnoted with its own FY; a sort toggle orders both the level
chart and its YoY companion identically. Bars radius 2.

CHART-ALIGNMENT RULE: paired charts (earnings-quality / capex intensity) share identical
container height, margin, and XAxis height so their FY category axes sit on one baseline.

NEVER: pies, 3D, gradients (beyond the 8% area), rainbow palettes, animated chart intros, or a second VISIBLE
y-axis (a hidden companion axis for a background series like volume is fine; two labelled axes that invite
misreading are not).

## States and motion
Every remote panel: skeleton (surface-2 pulse blocks matching final geometry) -> content | empty (one plain
sentence + what would fill it) | error (one sentence + Retry button). Never a raw alert box. Q&A: thinking =
subtle 3-dot pulse; declined answers use warn tint + decline_reason, visually distinct from errors; the send
button shows a spinner while thinking. A backend-optional section (e.g. the AI risk summary) shows a skeleton
while loading and hides ENTIRELY on any non-200. Motion: 150ms ease-out on hover/sheet/accordion; nothing
bouncy; respect prefers-reduced-motion.

## Voice
Sentence case everywhere. Labels name what the user recognises ("Trailing P/E", "What changed in risk
factors"), never internals ("riskdiff service"). Empty/error copy states the fact and the next action,
no apologies, no exclamation marks.

## Self-check before finishing any UI task
1 Contrast pairs all from the token list? 2 Numbers tabular + right-aligned + formatted per rules?
3 FY labels present on every fiscal value? 4 Skeleton/empty/error handled? 5 Focus visible? 6 Per-ticker
colours consistent (and non-colliding)? 7 Delta colours follow the polarity map? 8 Paired charts aligned?
9 Anything decorative to delete?
