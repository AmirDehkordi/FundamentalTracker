# Design writeup

Companion to [`PLAN.md`](../PLAN.md), the frozen pre-build plan, and the [README](../README.md),
which covers quickstart, configuration, and eval evidence. This is the as-built account, organised
around six questions: architecture and data model; source integration; where the
LLM is and is not; backend, UI, and persistence choices; the two custom metrics; and the tradeoffs
behind what was deliberately cut.

## 1. Architecture and data model

All outbound traffic is confined to `ingestion/`: one shared EDGAR client (declared User-Agent,
throttled below 8 requests per second, backoff retries) plus yfinance with a stooq fallback for
prices. Every raw response is cached under `seed/bronze/`, so `--from-cache` replays the entire
pipeline offline. Ingestion writes Postgres 16 (`companies`, `fundamentals`, `prices`, `filings`,
`filing_chunks`, `insider_transactions`), and a committed `pg_dump` restores automatically through
`docker-entrypoint-initdb.d` — a cold clone serves real data without a single live API call.

Above the database, `services/` holds pure, typed, unit-tested functions with no HTTP and no LLM.
Both `api/` (FastAPI) and `agent/` (the tool-calling loop) are thin callers of those same functions,
so a number plotted in a chart and a number cited in an answer share one code path by construction.

Two data-model decisions carry most of the weight. First, provenance: every fundamental row records
`accession`, `filed`, `form`, and `source_tag`, the last admitting `derived:…` for computed
concepts. Restatements resolve latest-filed-wins, but the replaced value is retained in
`superseded_value` / `superseded_filed` rather than discarded — a tooltip or an agent citation can
say "restated, originally 11.93" instead of silently rewriting history. That same mechanism is what
keeps per-share facts split-consistent inside the newest filing's comparative window: NVDA's FY2024
EPS surfaces as the post-split 1.19 with the pre-split 11.93 kept as the superseded value. Outside
that window stored values keep their as-filed basis; a read-time guard suppresses per-share YoY
across the resulting basis break (§6). Second, fiscal alignment: `fiscal_year` is derived as `year(period_end)` rather than
trusted from EDGAR's own `fy`/`fp` fields, which describe the report a fact appeared in, not the
period the fact covers. AAPL's FY2022 revenue surfaces tagged fy=2022, 2023, and 2024 across
successive filings; trusting the tag would silently conflate three different fiscal years in any
cross-company comparison.

## 2. Three-source integration and the trailing-P/E cross-source join

XBRL `companyfacts` supplies the structured backbone, resolved through a tag-fallback chain
evaluated per `(company, fiscal year)` — per year, not per company, because GOOGL switched from
contract revenue to bare `Revenues` starting FY2025, and a company-level "first tag with data" pick
would silently drop its latest year. Where a company does not tag a concept directly, two are
derived (gross profit for GOOGL and ETN; operating income for ETN after FY2019), always
provenance-tagged `derived:…`. EDGAR submissions supply the narrative — Items 1A and 7 of the two
most recent 10-Ks, extracted past a table-of-contents false match — and Form 4 insider transactions
(purchase and sale codes only, with the XSL-wrapper path stripped to reach the raw XML). Prices come
from yfinance, split- and dividend-adjusted, with stooq as a fallback behind the same interface.

The cross-source join lives in `services/valuation.py`. Trailing P/E is the latest stored close
divided by diluted EPS of the latest reported fiscal year, joined ticker → CIK across the prices and
fundamentals tables. The payload states both bases explicitly — `price_as_of` on one side, the EPS
row's `(fiscal_year, period_end, accession)` on the other — so the UI and any agent citation render
"P/E 54.3× (FY2025 EPS, ended 27 Sep 2025 · price as of 3 Jul 2026)" rather than implying a single
"current" number drawn from two different clocks. Non-positive EPS returns `None` with the reason
"n.m. — negative EPS"; never a crash, never a fabricated ratio.

## 3. Where the LLM is, where it is not, and why

The LLM routes a question to tools, composes cross-modal answers, summarises retrieved narrative and
the risk-factor diff on demand, produces the final structured answer, and asks a single clarifying
question when the question is genuinely ambiguous. It never issues HTTP or SQL, never computes or
transforms a number — every metric lives in `services/` and is unit-tested — and it sits nowhere in
the dashboard render path. Every figure a user sees, in a panel or in an answer, originates from a
deterministic tool result; the model narrates what it was handed.

The risk-factor diff is the clearest illustration. The year-over-year diff of Item 1A is fully
deterministic: paragraphs are matched by best `SequenceMatcher` ratio, since position-based diffing
degenerates once a filing reorders sections, and the output is exact added and removed excerpts with
counts. The LLM's role is a contained expansion on top. A three-stage pipeline drafts candidate
themes from those excerpts alone, critiques them against a coverage report computed in Python, and
finalizes the top themes — grounded structurally, because the model never sees anything beyond the
supplied excerpts, and enforced in code, because every citation index is checked in range. Results
are cached by filing pair and content hash, so a repeated question costs no LLM calls, and the
endpoint returns 503 rather than 500 when no LLM is configured and the cache misses.

That shape — deterministic computation underneath, the LLM narrating on top, grounding enforced in
code rather than trusted from the model — recurs throughout the agent. `FinalAnswer.kind`
(`answer` / `clarification` / `decline` / `error`) is a real code-level dispatch, not a prompt
convention, and a code-level guard retries any answer that contains digits but carries an empty
citation list before it ever reaches the user.

## 4. Backend, UI, and persistence choices

**Postgres over SQLite.** The retrieval path — GIN-indexed `tsvector` with `ts_rank` and
`ts_headline` — feeds the agent's citations directly, and Compose plus a committed `pg_dump` keeps
cold start at one command without giving up a real full-text engine.

**FastAPI over Flask or Django.** Typed Pydantic contracts, OpenAPI-generated TypeScript types, and
`/docs` for free — and the agent's tool schemas are generated from the same request and response
models the API serves.

**React + Vite + TypeScript over Streamlit or Dash.** A dense analyst dashboard needs real layout
control. The frontend builds to static files served by FastAPI, so the whole application ships as
one container. It follows a single audited dark theme (`.claude/skills/dashboard-design/`) with a
merge-blocking 4.5:1 contrast rule and tabular numerals on every figure — one theme done properly
beats two done halfway.

**A hand-rolled agent loop (~200 lines) over a framework.** LangGraph is the author's production
default, deliberately not used here: the behaviour that matters most — routing, grounding, refusal — should be
legible by reading one file, not traced through a framework's internals.

## 5. The two custom metrics

**FCF margin and FCF conversion** (FCF ÷ revenue; FCF ÷ net income) read earnings quality. Accrual
and cash earnings diverge through stock-based compensation, working-capital swings, and capex
cycles; conversion at or above 1.0 says reported profit is actually turning into cash.

**Capex intensity and reinvestment ratio** (capex ÷ revenue; capex ÷ CFO) read capital intensity.
Both are computed from concepts already ingested — no new ingestion — and guarded None-with-reason
on a non-positive denominator.

The pairing is deliberate rather than two disconnected ratios: rising capex intensity is the
mechanical driver of FCF-margin compression, since capex is subtracted from CFO to get FCF. Read
side by side on the Overview, the two cards answer the live question for this universe — is the
AI-infrastructure build-out outrunning the cash the business generates? Four of the five names sit
on that cycle from different seats, which is what makes capital deployment the most
decision-relevant variable for this particular universe: the hyperscaler spenders (MSFT and GOOGL,
both near 23% capex intensity in the latest fiscal year); the beneficiary whose revenue is, to a
first order, the other names' capex (NVDA, itself ~3% — its own capex is R&D and office footprint
rather than data-center build); the power-infrastructure supplier selling into the build-out
(ETN, ~3%); and the asset-light control case (AAPL, ~3%). This pair replaced an earlier candidate,
operating leverage (ΔOpInc ÷ ΔRevenue) — a valid trajectory metric, but less decision-relevant in
the current capex cycle than one causally linked to the FCF-quality card beside it.

## 6. Tradeoffs and deliberate cuts

**Product surface, cut for scope discipline.** Streaming answers (polish, not core; a thinking
indicator covers the 20–60s latency). Auth and multi-user (an internal single-analyst prototype). A
light theme (one audited theme beats two half-audited ones). Live intraday prices (daily close is
the valuation basis; freshness is labelled rather than implied). Multi-turn chat history in Q&A —
single-turn keeps every answer independently grounded and citable, where conversation state would
let an ungrounded follow-up lean on a prior answer instead of a tool result. Scheduled refresh — a
production tracker would poll EDGAR submissions for new 10-Ks and re-pull prices on a schedule;
ingestion here is a manual command, but it is idempotent on natural keys, so a scheduler is a cron
entry away rather than a redesign, and for a fresh clone the committed seed is the freshness contract.

**Data model, cut for honesty about what a prototype should promise.** Alembic migrations — the
schema ships once with a seed, and `create_all` plus `pg_dump` is honest for this scope rather than
a shortcut concealing production intent. Point-in-time, as-first-reported history — a quant shop
would want lookahead-safe history, and latest-filed-wins loses it, but the `superseded_*` columns
and the bronze cache keep that door open. Quarterly fundamentals — annual data answers every
acceptance question, and quarters double the fiscal-alignment complexity for no added benefit.

**Split back-adjustment outside the comparative window — a named cut with a shipped mitigation.**
Latest-filed-wins keeps per-share facts split-consistent only for the fiscal years the newest 10-K
restates as comparatives. Deterministically back-adjusting older facts (EPS ÷ split factor, tagged
`|split-adjusted`) was planned and cut; stored values stay exactly as filed. The consequence,
stated plainly: NVDA's stored EPS levels span three share bases across the full history (FY2019
pre-all-splits; FY2020–22 on the 4:1 basis; FY2023 onward on the 10:1 basis). The shipped
mitigation is a read-time guard: when adjacent fiscal years' diluted shares jump ≥ 1.5× in either
direction, the `eps_diluted` and `shares_diluted` YoY cells are suppressed as "n.m. — share basis
change (stock split)" — surfaced in the table with the same tooltip affordance as restatements — so
a mixed-basis growth number is never rendered in a panel or handed to the agent. In-window figures
(the default four-year view's levels, and trailing P/E, which only ever uses the latest fiscal
year) are unaffected.

**Retrieval, cut after an explicit tradeoff.** Postgres full-text search over pgvector and
embeddings: at a corpus of roughly twenty sections, ranking-quality differences between FTS and
embeddings are noise; the agent can reformulate a failed query mid-loop, a luxury a human searcher
doesn't get; and an embedding model would add a second independent dependency behind an already
unknown provider or proxy. The honest failure mode — AND semantics on a paraphrase — is mitigated,
not eliminated; see the audit notes below.

**Scope, cut by design.** Forecasting and forward estimates — the refusal policy is the feature.
Tickers beyond the default five — the universe is config-driven and would generalise, but the
tracked set stays fixed. Form 4 derivative tables — non-derivative purchase
and sale codes carry the insider-sentiment signal; the rest is noise.

## Notes from the pre-release audit

A few fixes landed after the initial build and are worth stating explicitly:

- **Filing-search AND semantics.** The flagship failure mode was the model passing whole sentences
  as search queries, which get ANDed term by term, so a paraphrase returned zero hits. Fixed with a
  tool-contract change (2–5 keywords, never a sentence), a sanitizing retry ladder in
  `services/retrieval.py` (exact → relaxed OR → fuzzy substring on the rarest terms), and a one-shot
  corrective hint from the loop when a search comes back empty.
- **Transport retry and a fuller citation guard.** The OpenAI client originally carried no retry on
  transient errors, so one rate limit or connection blip failed an entire request; a single
  deadline-aware retry now covers rate-limit, connection, timeout, and internal-server errors.
  Separately, the citation-completeness retry checked only `filing` citations; it now also checks
  `fundamental` and `price`, which alone accounted for five of the seven failures in the previously
  committed eval run. Together the two fixes took the suite from 8/15 (core 3/6) to 15/15
  (core 6/6); both runs were posted sequentially (the harness spaces requests with an
  `EVALS_DELAY_S` pause).
- **Margin deltas in percentage points**, never relative change: a margin moving from 40% to 42% is
  reported as +2.0 pp, not +5%, under a dedicated `percentage_points` unit.
- **NVDA's capex tag discontinuity.** `PaymentsToAcquirePropertyPlantAndEquipment` stops after
  FY2012 and `PaymentsToAcquireProductiveAssets` picks up in FY2022; FY2013–FY2021 carry no annual
  capex tag at all. That is a genuine reporting gap in EDGAR, not a fallback-chain miss.
- **Identical insider 90-day and 365-day windows are correct, not a bug**, for companies whose
  entire Form 4 history falls inside the 90-day window (MSFT, GOOGL, and ETN in the committed seed):
  both windows aggregate the same rows by construction.
