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

### The risk-factor diff stays deterministic; the LLM only summarises it
The Item 1A year-over-year diff is computed in `services/riskdiff.py` with no LLM: paragraphs are
normalised (page furniture / sub-sentence fragments dropped, intra-year near-duplicates collapsed)
and paired by best `SequenceMatcher` ratio, yielding added/removed excerpts and exact counts. The
LLM's role is a **deliberate, contained expansion**: a new endpoint
`GET /api/companies/{ticker}/risk-diff/summary` feeds *that deterministic diff's excerpts* to one
grounded LLM call (`agent/riskdiff_summary.py`) asking for the top 3 newly added/heightened and top 3
removed/reduced risks, each a short title + detail. It is grounded structurally (the model sees only
the supplied excerpts), schema-validated with one retry, and cached in-process per `(cik, fy_pair)`.
No LLM key configured → the endpoint returns 503, never 500. The diff numbers a user sees are still
100% deterministic; only the prose summary is the model's.

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

## `operating_leverage` → `incremental_operating_margin`

The metric ΔOperatingIncome ÷ ΔRevenue **is** the incremental operating margin — how much of each new
revenue dollar reaches operating income. "Operating leverage" is a looser, overloaded term; the new
name says exactly what the number is, and the formula and guards are unchanged. The fundamentals
payload additionally exposes the per-FY dollar deltas `delta_revenue` and `delta_operating_income`
(unit USD) that the card plots as incremental bars.

## Margin YoY in percentage points

Margin/ratio YoY (gross/operating/net/FCF margin, FCF conversion) is reported as a **percentage-point
delta** (`curr − prev`) under a new `percentage_points` `MetricUnit`, distinct from a relative %
change: a margin moving 40%→42% is `+2.0 pp`, not `+5%`. Absolute levels keep their relative %-change
YoY. Adding the unit was a deliberate, contained unfreeze of `MetricUnit`; the frontend renders it
with a ` pp` suffix.

## Insider windows: identical 90d/365d is correct, not a bug

`services/insider.py` anchors both windows to the most recent Form 4 `filed` date (never "today", for
determinism) and measures 90 and 365 days back from it. When every Form 4 for a company falls within
90 days of that anchor — true for MSFT, GOOGL and ETN in the committed seed — the two windows contain
the same rows and their aggregates are legitimately identical. AAPL (~292-day span) and NVDA
(~104-day span) genuinely differ. A fixture test (`test_windows_differ_when_data_spans_more_than_90_days`)
pins that the windows are computed over genuinely different sets when the data spans more than 90
days. No windowing logic changed.
