---
name: dashboard-design
description: Design authority for the Fundamentals Tracker frontend. Use whenever creating or modifying any UI component, style, layout, chart, or state. Defines the dark theme tokens, contrast rules, layout map, typography, chart conventions, and interaction states.
---

# Dashboard design system — "quiet terminal"

Intent: an institutional analyst tool. Dense but calm; the data is the interface. One accent colour, spent
sparingly. If a choice feels decorative, delete it. The user is a PM/analyst deciding in seconds whether a
number matters — hierarchy, alignment, and labels do the work.

## Tokens (implement as CSS variables; map into Tailwind theme)
Backgrounds (dark grey, never pure black):
  --bg          #0B0F14   app background
  --surface-1   #11161D   cards, sidebar
  --surface-2   #171E27   hover, table row hover, chart tooltip, inputs
  --border      #232C37   1px hairlines everywhere; no shadows for elevation
Text (off-white, never pure white, NEVER dark-on-dark):
  --text-1      #E7ECF3   primary — 13:1 on surface-1
  --text-2      #A9B4C2   secondary/labels — 7:1
  --text-3      #7B8794   captions/hints only, min 12px — 4.6:1. Nothing dimmer than this, ever.
Accent (single, desaturated — saturated colours vibrate on dark):
  --accent      #6EA8FE   interactive: links, active tab, focus ring, primary button
  --accent-bg   #14243D   selected states, chips
Semantics (desaturated for dark):
  --pos #34D399  --neg #F87171  --warn #FBBF24   (deltas ALSO carry an arrow/sign — never colour alone)
Fixed per-ticker series colours (same everywhere: charts, compare, legends):
  NVDA #6EA8FE · MSFT #34D399 · AAPL #A78BFA · GOOGL #FBBF24 · ETN #F87171

HARD RULE — contrast: every text/background pair >= 4.5:1 (3:1 for >= 20px semibold). When adding ANY new
colour pairing, verify mentally against the token list; if it is not one of text-1/2/3 on bg/surface-1/2,
justify it. Dark or black text on dark surfaces is a build-breaking bug.

## Typography and numbers
Inter (fallback system-ui). Sizes only: 12 caption · 13 table body · 14 UI body · 16 card values-small ·
20 section · 24 KPI value. Weights 400/500/600 only. ALL numeric cells: font-variant-numeric: tabular-nums,
right-aligned. Formats: percents 1dp ("62.4%"); currency adaptive ("$130.5B", "$964M"); ratios 1dp ("54.3x");
undefined -> em dash + tooltip reason ("n.m. — negative EPS"). Every fiscal value is labelled
"FY2025 (ended 27 Sep 2025)" — the label is a feature, not clutter.

## Layout map (desktop-first, min 1280px; content max 1440px, 12-col grid, 16px gutters, 4px spacing base)
┌ sidebar 232px ┬ top bar 56px ──────────────────────────────┬ Q&A Sheet 400px (slide-over) ┐
│ product name  │ company name+ticker · FY chip · trailing   │ chips · thread · input       │
│ 5 companies   │ P/E · freshness · [Ask]                     │ citations · trace accordion  │
│ (ticker bold, ├ Tabs: Overview | Compare ───────────────────┤                              │
│  name muted,  │ Overview: KPI row (5 cards)                 │                              │
│  FY badge)    │ fundamentals table 7/12 · price chart 5/12  │                              │
│ freshness ftr │ earnings-quality · op-leverage · insider ·  │                              │
│               │ risk-diff cards (row 3)                     │                              │
└──────────────┴─────────────────────────────────────────────┴──────────────────────────────┘
Reading order = importance: identity -> headline KPIs -> detail table/trend -> analytical cards. One
question per view; drill-down via expand, not navigation. Q&A is a slide-over so the data stays visible
while asking.

## Components (shadcn/ui: Tabs, Card, Table, Badge, Button, Sheet, Select, Skeleton, Tooltip, Accordion,
ScrollArea, Separator)
Cards: surface-1, 1px border, radius 10, padding 16, header = 12px uppercase tracking-wide text-2 + optional
Tooltip "i". KPI card: label(12/text-2) -> value(24/600/text-1) -> delta chip(12: arrow+sign+% on
pos/neg tint bg) -> FY sublabel(12/text-3). Tables: header row 12px uppercase text-2, rows 38px, hover
surface-2, first column sticky, hairline row borders only. Sidebar item: 40px, active = accent-bg tint +
2px accent left bar. Focus: 2px accent ring, always visible, on every interactive element.

## Charts (Recharts)
Grid: horizontal only, --border, dashed 3-3. Axes: 12px text-3, no axis lines. Tooltip: surface-2, border,
full precision + date. Price chart: 1.5px accent line, optional area fill accent at 8% opacity; range
segmented control [1M 6M 1Y 2Y MAX]; 10-K filing dates = ReferenceLine (--border, dashed) + tiny "10-K"
label (text-3). Compare: grouped bars, per-ticker fixed colours, value labels 12px, each bar footnoted with
its own FY label. Bars radius 2. NEVER: pies, 3D, gradients (beyond the 8% area), dual axes, rainbow
palettes, animated chart intros.

## States and motion
Every remote panel: skeleton (surface-2 pulse blocks matching final geometry) -> content | empty (one plain
sentence + what would fill it) | error (one sentence + Retry button). Q&A: thinking = subtle 3-dot pulse;
declined answers use warn tint + decline_reason, visually distinct from errors. Motion: 150ms ease-out on
hover/sheet/accordion; nothing bouncy; respect prefers-reduced-motion.

## Voice
Sentence case everywhere. Labels name what the user recognises ("Trailing P/E", "What changed in risk
factors"), never internals ("riskdiff service"). Empty/error copy states the fact and the next action,
no apologies, no exclamation marks.

## Self-check before finishing any UI task
1 Contrast pairs all from the token list? 2 Numbers tabular + right-aligned + formatted per rules?
3 FY labels present on every fiscal value? 4 Skeleton/empty/error handled? 5 Focus visible? 6 Per-ticker
colours consistent? 7 Anything decorative to delete?
