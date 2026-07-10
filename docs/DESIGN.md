# Design writeup

Companion to [`PLAN.md`](../PLAN.md) (the frozen pre-build plan) and the [README](../README.md)
(quickstart, environment, models). This is the as-built account, organised around the brief's six
questions: architecture and data model; source integration; where the LLM is and isn't; backend/UI/
persistence choices; the two own metrics; tradeoffs and cuts.

## 1. Architecture and data model

`ingestion/` is the only module that talks to the outside world — one shared EDGAR client (declared
User-Agent, ≤8 req/s throttle, backoff retries) plus yfinance/stooq for prices — and every raw
response is bronze-cached under `seed/bronze/`, so `--from-cache` replays the full pipeline offline.
It writes Postgres 16 (`companies`, `fundamentals`, `prices`, `filings`, `filing_chunks`,
`insider_transactions`); a committed `pg_dump` auto-restores via `docker-entrypoint-initdb.d`, so a
cold clone serves real data with zero live API calls. `services/` reads the DB with pure, typed,
unit-tested functions — no HTTP, no LLM — and `api/` (FastAPI) and `agent/` (the tool-calling loop)
are both thin callers of those same functions, so a number computed for a chart and a number cited in
an answer are, by construction, the same code path.

Every fundamental row carries provenance: `accession`, `filed`, `form`, and `source_tag` (admitting
`derived:…` for computed concepts and `|split-adjusted` for back-adjusted per-share facts).
Restatements resolve latest-filed-wins, but the replaced value is kept in `superseded_value` /
`superseded_filed` rather than discarded — so a UI tooltip or an agent citation can say "restated,
originally 11.93" instead of silently overwriting history. `fiscal_year` is derived as
`year(period_end)`, not trusted from EDGAR's own `fy`/`fp` fields, which describe the *report* a fact
appeared in, not the fact's period — AAPL's FY2022 revenue turns up labelled fy=2022, 2023, *and* 2024
across successive filings. Getting this wrong would silently mislabel three different fiscal years as
the same one in any cross-company comparison.

## 2. Three-source integration and the trailing P/E cross-source join

XBRL `companyfacts` supplies the structured backbone, resolved through a per-`(company, fiscal year)`
tag-fallback chain — evaluated per year, not per company, because GOOGL switched from contract revenue
to bare `Revenues` starting FY2025; a company-level "first tag with data" pick would silently drop its
latest year. Two concepts are derived where a company doesn't tag them directly (gross profit for
GOOGL/ETN; operating income for ETN post-FY2019), always provenance-tagged `derived:…`. EDGAR
submissions supply the narrative (Items 1A/7 of the two most recent 10-Ks, extracted past a
table-of-contents false match) and Form 4 insider transactions (P/S codes only, XSL-wrapper path
stripped to reach the raw XML). Prices come from yfinance (split/dividend-adjusted), falling back to
stooq behind the same interface.

The cross-source join lives in `services/valuation.py`: trailing P/E is `close(max stored date) ÷
eps_diluted(latest reported FY)`, joined ticker → CIK across the prices and fundamentals tables. The
payload carries both bases explicitly — `price_as_of` and the EPS row's `(fiscal_year, period_end,
accession)` — so the UI and any agent citation render "P/E 54.3× (FY2025 EPS, ended 27 Sep 2025 · price
as of 3 Jul 2026)" rather than implying a single "current" number from two different clocks. EPS ≤ 0
returns `None` with reason "n.m. — negative EPS", never a crash or a fabricated ratio.

## 3. Where the LLM is / is not, and why

**Is:** routing a question to tools, composing cross-modal answers, summarising retrieved narrative
and the risk-factor diff on demand, producing the final structured answer, and asking one clarifying
question when a question is genuinely ambiguous. **Is not:** it never issues HTTP or SQL, never
computes or transforms a number — every metric lives in `services/` and is unit-tested — and it is
nowhere in the dashboard render path. Every figure a user sees, in a panel or an answer, originates
from a deterministic tool result; the LLM only narrates results it was handed, never invents them.

The clearest example is the risk-factor diff. The Item 1A year-over-year diff itself is 100%
deterministic — paragraphs matched by best `SequenceMatcher` ratio (position-based diffing degenerates
once a filing reorders sections), yielding exact added/removed excerpts and counts, no LLM involved.
The LLM's role is a deliberate, contained expansion: a 3-stage pipeline drafts candidate themes from
*only those excerpts*, critiques them against a Python-computed coverage report, and finalizes the top
themes — grounded structurally (the model never sees anything but the supplied excerpts) and enforced
in Python (every citation index checked in range). Results are cached by filing-pair + content hash, so
a repeat question costs zero LLM calls, and the endpoint returns 503 rather than 500 if no LLM is
configured and there's no cache hit. This pattern — deterministic computation, LLM narrates on top,
grounding enforced in code rather than trusted from the model — is the same shape as the rest of the
agent: `FinalAnswer.kind` (`answer`/`clarification`/`decline`/`error`) is a real code-level dispatch,
not a prompt convention, and a code-level check retries any answer containing digits with an empty
citation list before it ever reaches the user.

## 4. Backend/UI/persistence choices

Postgres over SQLite: the retrieval path (`ts_rank`/`ts_headline`/GIN-indexed `tsvector`) feeds the
agent's citations directly, and `compose` + a committed `pg_dump` keep cold start at one command
without giving up a real full-text engine. FastAPI over Flask/Django: typed Pydantic contracts,
OpenAPI-generated TypeScript types, `/docs` for free, and the same request/response models the agent's
tool schemas are generated from. React + Vite + TS over Streamlit/Dash: analyst-grade layout control
for a dense dashboard, built to static files and served by FastAPI so the whole thing ships as one
container. The agent loop is hand-rolled (~200 lines) rather than a framework (LangGraph is the
author's production default, deliberately not used here) because the graded behaviour — routing,
grounding, refusal — needs to be legible by reading one file, not traced through a framework's
internals. The frontend follows a single audited dark theme (`.claude/skills/dashboard-design/`) with
a review-blocking 4.5:1 contrast rule and tabular-nums on every numeral — one theme done properly beats
two done halfway.

## 5. The two own metrics

**FCF margin + FCF conversion** (FCF ÷ revenue; FCF ÷ net income) is an earnings-quality read:
accrual earnings and cash earnings diverge through stock-based comp, working-capital swings, and capex
cycles, and conversion near or above 1.0 says reported profit is actually turning into cash.

**Capex intensity + reinvestment ratio** (capex ÷ revenue; capex ÷ CFO) is a capital-intensity read,
computed from concepts already ingested — zero new ingestion — and guarded None-with-reason on a
non-positive denominator.

They're paired deliberately, not just two disconnected ratios: rising capex intensity is the mechanical
driver of FCF-margin compression (capex is subtracted from CFO to get FCF), so reading the two Overview
cards side by side answers the live question for this universe directly — is the AI-infrastructure
build-out outrunning the cash the business generates? It separates the hyperscaler spenders (MSFT,
GOOGL, both ~23% capex intensity in the latest FY) from the AI-demand receiver (NVDA, ~3%, where capex
is R&D/office footprint rather than data-center build), the power-infrastructure beneficiary (ETN,
~3%, a supplier into the build-out rather than a builder), and the asset-light abstainer (AAPL, ~3%).
This pair replaced an earlier own metric, operating leverage (ΔOpInc ÷ ΔRevenue) — a valid trajectory
metric, but less decision-relevant for this universe in the current capex cycle than a metric causally
linked to the FCF-quality card next to it.

## 6. Tradeoffs and deliberate cuts

**Product surface, cut for scope discipline:** streaming answers (polish, not graded — the thinking
indicator covers the 20–60s latency); auth/multi-user (internal single-analyst prototype); a light
theme (one audited theme beats two half-audited ones); live/intraday prices (daily close is the
valuation basis; freshness is labelled instead of implied).

**Data model, cut for honesty about what a prototype should promise:** Alembic migrations (schema
ships once with a seed — `create_all` + `pg_dump` is honest for this scope, not a shortcut hiding
production intent); point-in-time / as-first-reported history (a real quant shop would want
lookahead-safe history; latest-filed-wins loses it, but the `superseded_*` columns and bronze cache
keep the door open); quarterly fundamentals (annual answers every acceptance question; quarters double
the fiscal-alignment complexity for no graded benefit).

**Retrieval, cut after an explicit tradeoff:** pgvector/embeddings, in favour of Postgres full-text
search — at a ~20-section corpus, ranking-quality differences between FTS and embeddings are noise, the
agent can reformulate a failed query mid-loop (a luxury a human searcher doesn't get), and an embedding
model would be a second, independent dependency behind an already-unknown review-time proxy. The
honest failure mode (AND-semantics on a paraphrase) is mitigated, not eliminated — see the audit notes
below.

**Scope, cut because the brief draws the line there:** forecasting/forward estimates (the refusal
policy *is* the feature); tickers beyond the graded five (the universe is config-driven and would
generalise, but the graded set stays fixed); Form 4 derivative transaction tables (non-derivative P/S
codes only — the rest is noise for an insider-sentiment signal).

## Notes from the pre-submission audit

A few fixes landed after the initial build that are worth flagging explicitly rather than leaving
buried in commit history:

- **Filing search AND-semantics.** The flagship failure mode was the model passing whole sentences as
  a search query, which get ANDed term-by-term — a paraphrase then returns zero hits. Fixed with a
  tool-contract change (2–5 keywords, never a sentence), a sanitizing retry ladder in
  `services/retrieval.py` (exact → relaxed OR → fuzzy substring on the rarest terms), and a one-shot
  corrective hint from the loop when a search comes back empty.
- **Deadline-aware transport retry + fuller citation-completeness check.** The OpenAI client originally
  had no retry on transient errors, so one rate limit or connection blip failed an entire request; a
  single deadline-aware retry now covers `RateLimitError`/`APIConnectionError`/`APITimeoutError`/
  `InternalServerError`. Separately, the citation-completeness retry only checked for `filing`
  citations — it now also checks `fundamental` and `price`, closing the largest source of eval
  failures under concurrent load (see the README's Q&A Eval Results for the before/after).
- **Margin YoY in percentage points**, not relative percent change — a margin moving 40%→42% is
  reported as `+2.0 pp`, never `+5%`, under a dedicated `percentage_points` unit.
- **NVDA's capex tag discontinuity**: `PaymentsToAcquirePropertyPlantAndEquipment` stops after FY2012,
  `PaymentsToAcquireProductiveAssets` picks up in FY2022; FY2013–FY2021 carry no annual capex tag at
  all — a genuine reporting gap in EDGAR, not a fallback-chain miss.
- **Insider 90d/365d windows being identical is correct, not a bug**, for companies (MSFT, GOOGL, ETN
  in the committed seed) whose entire Form 4 history falls inside the 90-day window — both windows
  aggregate the same rows by construction.
