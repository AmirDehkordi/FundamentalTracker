# Design notes

Companion to `PLAN.md` (the pre-build plan). This records where the design landed after the
pre-submission audit fixes to the natural-language layer and the supporting backend. `PLAN.md` stays
the frozen plan; this is the "as-built" for the decisions that moved.

## Where the LLM is / is not

**The LLM is:** routing a question to tools; composing cross-modal answers; **summarising retrieved
narrative and the risk-factor diff on demand**; producing the final structured answer; and — new in
this chunk — deciding when a question is too ambiguous to answer and asking one clarifying question
instead.

**The LLM is not:** it never issues HTTP or SQL, never computes or transforms a number (every metric
lives in `services/` and is unit-tested), and is nowhere in the dashboard render path. Every figure a
user sees, in a panel or an answer, originates from a deterministic tool result.

### The risk-factor diff stays deterministic; the LLM only clusters it into themes
The Item 1A year-over-year diff is computed in `services/riskdiff.py` with no LLM: paragraphs are
normalised (page furniture / sub-sentence fragments dropped, intra-year near-duplicates collapsed)
and paired by best `SequenceMatcher` ratio, yielding added/removed excerpts and exact counts. The
LLM's role is a **deliberate, contained expansion**: `GET /api/companies/{ticker}/risk-diff/themes`
feeds *that deterministic diff's excerpts* to a 3-stage pipeline (`agent/riskdiff_themes.py`) — draft
candidate themes, critique/ground them against a Python-computed coverage report, finalize the top 3
added/heightened and top 3 removed/reduced themes. Grounded structurally (the model sees only the
supplied excerpts) and enforced in Python (every citation index in range), then persisted to the
`risk_themes` table (`services/risk_theme_cache.py`) keyed by the filing pair + a content hash, so a
cache hit costs zero LLM calls. No LLM configured and no cache hit → the endpoint returns 503, never
500. The diff numbers a user sees are still 100% deterministic; only the theme clustering is the
model's.

## Filing search: keyword hardening + a retry ladder

The flagship failure was AND-semantics: the model passed whole sentences as the `search_filings`
query and every term was ANDed, so a paraphrase returned zero hits and the agent apologised. Fixed in
three layers:

- **Tool contract + prompt** instruct 2–5 content keywords (never a sentence) and permit multiple
  searches with different keywords when a result is thin.
- **`services/retrieval.py`** sanitises the query (strip punctuation/stopwords, cap ~6 terms) and runs
  a retry ladder — `exact` (strict AND) → `relaxed` (OR of the keywords) → `fuzzy` (substring on the
  two rarest keywords) — reporting which rung matched so the trace can show "relaxed search". Each
  rung is unit-tested on SQLite; the real Postgres SQL is covered by the integration job.
- **`agent/loop.py`** injects one corrective hint if a search returns 0 hits and the model has not
  retried, giving it a chance to reformulate before it gives up.

## Clarification vs decline vs error (`FinalAnswer.kind`)

`FinalAnswer` gains `kind` (`answer` | `clarification` | `decline` | `error`) and
`suggested_followups`; the legacy `declined` flag is kept and derived (`kind ∈ {decline, error}`) for
backward compatibility. An ambiguous, under-specified question now yields **one conversational
clarifying question** (`kind="clarification"`) with 2–3 natural-language follow-ups, never machine
copy and never quoting the user's typos; declines keep their polite one-liner and also offer 1–2
in-scope follow-ups. Loop/endpoint failures are `kind="error"`. The citation-enforcement retry now
fires only for real `answer`s, so a clarification containing a digit is never pressured to cite.

## Own metrics: FCF quality, paired with capex intensity

The two own metrics tell one causally-linked story rather than two disconnected ratios:

- **FCF margin + FCF conversion** (earnings quality) — free cash flow ÷ revenue, and free cash flow ÷
  net income. Conversion near or above 1.0 says reported profit is turning into cash.
- **Capex intensity + reinvestment ratio** (capital intensity) — `capex_intensity` = capex ÷ revenue,
  `reinvestment_ratio` = capex ÷ CFO. Both are pure functions of concepts already ingested (capex,
  revenue, cfo — zero new ingestion), guarded None-with-reason on a non-positive denominator
  (`REASON_CAPEX_INTENSITY_UNDEFINED` / `REASON_REINVESTMENT_UNDEFINED`).

They are paired deliberately: rising capex intensity is the mechanical driver of FCF-margin
compression (capex is subtracted from CFO to get FCF), so reading the two Overview cards side by side
answers the current-cycle question directly — is the AI infrastructure build-out outrunning the cash
the business generates? Across this universe it separates the hyperscaler spenders (MSFT, GOOGL, both
~23% capex intensity in the latest FY) from the AI-demand receiver (NVDA, ~3%, whose capex is R&D/office
footprint rather than data-center build-out), the power-infrastructure beneficiary (ETN, ~3%, a supplier
into the same build-out rather than a builder), and the asset-light abstainer (AAPL, ~3%).

This replaces the previous own metric, `operating_leverage`/`incremental_operating_margin`
(ΔOperatingIncome ÷ ΔRevenue) — see PLAN.md §12 decision log for why. `incremental_operating_margin`,
`delta_revenue`, and `delta_operating_income` are removed from the fundamentals payload; nothing else
depended on them.

## Margin YoY in percentage points

Margin/ratio YoY (gross/operating/net/FCF margin, FCF conversion) is reported as a **percentage-point
delta** (`curr − prev`) under a new `percentage_points` `MetricUnit`, distinct from a relative %
change: a margin moving 40%→42% is `+2.0 pp`, not `+5%`. Absolute levels keep their relative %-change
YoY. Adding the unit was a deliberate, contained unfreeze of `MetricUnit`; the frontend renders it
with a ` pp` suffix.

## Capex tag fallback (NVDA)

NVDA's 10-Ks stopped tagging `PaymentsToAcquirePropertyPlantAndEquipment` after FY2012 and picked up
`PaymentsToAcquireProductiveAssets` — a combined PP&E + intangible-asset-purchases line — starting
FY2022; FY2013-FY2021 carry no annual capex tag at all (a genuine reporting gap, not a fallback miss).
`capex` joined `gross_profit`/`operating_income` as a concept needing a per-company tag fallback chain,
the same pattern as GOOGL's derived gross profit.

## Insider windows: identical 90d/365d is correct, not a bug

`services/insider.py` anchors both windows to the most recent Form 4 `filed` date (never "today", for
determinism) and measures 90 and 365 days back from it. When every Form 4 for a company falls within
90 days of that anchor — true for MSFT, GOOGL and ETN in the committed seed — the two windows contain
the same rows and their aggregates are legitimately identical. AAPL (~292-day span) and NVDA
(~104-day span) genuinely differ. A fixture test (`test_windows_differ_when_data_spans_more_than_90_days`)
pins that the windows are computed over genuinely different sets when the data spans more than 90
days. No windowing logic changed.
