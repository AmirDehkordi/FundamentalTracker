# Fundamentals Tracker

A dashboard tracking SEC-filing fundamentals + market data for a small configurable universe, with a
grounded LLM Q&A layer.

[![CI](https://github.com/AmirDehkordi/Amir_Dehkordi_QuantDev_CaseStudy/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirDehkordi/Amir_Dehkordi_QuantDev_CaseStudy/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AmirDehkordi/Amir_Dehkordi_QuantDev_CaseStudy/branch/main/graph/badge.svg)](https://codecov.io/gh/AmirDehkordi/Amir_Dehkordi_QuantDev_CaseStudy)

## Screenshots

Overview — per-company fundamentals (fiscal labels, restatements, and a per-metric polarity map on
deltas), a price trend with a 150-day moving average + volume sub-panel, insider activity, and
risk-factor changes:

![Overview — Microsoft](docs/img/overview-msft.png)
![Overview — NVIDIA](docs/img/overview-nvda.png)

Compare — one metric across the universe on each company's latest reported fiscal year (left) and its
year-over-year change (right), sorted high-to-low:

![Compare](docs/img/compare.png)

Ask — grounded natural-language Q&A with source citations and a tool trace, in a non-modal side panel:

![Ask — grounded Q&A](docs/img/qa.png)

## Quickstart

```bash
cp .env.example .env    # then set LLM_BASE_URL / LLM_API_KEY / LLM_MODEL — see Environment below
docker compose up
open http://localhost:8000
```

A cold clone serves a fully populated dashboard from the committed seed alone — no live EDGAR/Yahoo
calls happen at startup. Only `/api/ask` needs a working LLM endpoint.

## Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `DATABASE_URL` | yes | Postgres connection string (psycopg 3 driver) |
| `LLM_BASE_URL` | yes | OpenAI-compatible endpoint the agent calls (Chat Completions surface) |
| `LLM_API_KEY` | yes | API key for that endpoint |
| `LLM_MODEL` | yes | Model id to request |
| `SEC_USER_AGENT` | yes | `"Name email (purpose)"` — SEC requires a declared UA on every EDGAR request |
| `UNIVERSE` | no | Comma-separated tickers; defaults to the fixed five (`NVDA,MSFT,AAPL,GOOGL,ETN`) |

To point at **Schonfeld's proxy** at review time, set `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` to
the proxy's values — in `.env` for `make run`, or as environment overrides for `docker compose up` —
no code change required. The agent talks plain Chat Completions to whatever `base_url` it's given
(`backend/src/tracker/agent/llm.py`), which is the interface every proxy and alternative provider
implements; that's also what makes the Groq swap below possible.

## Models

Pinned model: **`gpt-5.5`** — the current GA flagship reasoning model, requested over the standard
OpenAI-compatible Chat Completions surface. Eval evidence (15 questions incl. the brief's 6,
machine-checked against tool traces, citations, and numeric ground truth — full per-question
breakdown in [Q&A Eval Results](#qa-eval-results) below):

- `gpt-5.5` — **15/15** passed, brief **6/6** ([evals/last_run.md](evals/last_run.md))

The structured-output transport ladder (`response_format: json_schema` → `final_answer` tool call →
`json_object` + validate-and-retry, in `backend/src/tracker/agent/loop.py`) exists precisely because an
unknown review-time proxy's capabilities can't be assumed — it's designed to be proven by pointing the
same `.env` vars at a second, unrelated provider with zero code changes.

## Examples

See the screenshots above for the Overview, Compare, and Ask interactions. One copy-pasteable request
against a running `/api/ask`:

```bash
curl -s -X POST http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is AAPL trailing P/E right now?", "history": []}' | python3 -m json.tool
```

## Q&A Eval Results

`evals/questions.yaml` checks the agent loop (`backend/src/tracker/agent/loop.py`) against 15
natural-language questions — the 6 verbatim from the case-study brief plus 9 extra edge cases
(reworded phrasing, out-of-universe tickers, ambiguous questions, forward-looking declines).
`evals/run.py` posts each to a live `/api/ask`, checks routing (tools called), refusal behavior,
citation completeness, and answer content, then writes the table below to `evals/last_run.md` — run
it yourself with `make evals`.

**Latest run — `gpt-5.5`, 15/15 passed, brief 6/6, all 15 fired concurrently:**

| Metric | Value |
|---|---|
| Pass rate | 15/15 (100%) — brief 6/6 (100%) |
| Avg latency | 17.6s (median 16.0s, range 6.4s–35.3s) |
| Avg tokens/question | 7,033 (range 3,893–10,865) |
| Total tokens (15 questions) | 105,488 |
| Concurrent-load failures | 0/15 |

| ID | Category | Question | Tools called | Result | Latency | Tokens |
|---|---|---|---|---|---|---|
| brief-1-fundamentals | structured | NVDA revenue & net income, last 3 FYs | `get_fundamentals` | PASS | 16.0s | 7,818 |
| brief-2-compare-gross-margin | comparative | Highest gross margin across the 5 companies | `compare_companies` | PASS | 11.5s | 7,237 |
| brief-3-valuation-aapl-pe | valuation | AAPL trailing P/E | `get_valuation` | PASS | 6.4s | 6,688 |
| brief-4-risk-diff-nvda | filing text | New NVDA risk factors vs. prior 10-K | `diff_risk_factors` | PASS | 24.9s | 10,125 |
| brief-5-msft-revenue-and-mdna | cross-modal | MSFT revenue growth + management's attribution | `get_fundamentals`, `search_filings` | PASS | 35.3s | 10,865 |
| brief-6-forward-guidance-declined | out-of-scope decline | Forward guidance for next quarter | — | PASS | 6.5s | 3,972 |
| extra-7-compare-gross-margin-reworded | comparative | Widest gross margin (reworded) | `compare_companies` | PASS | 10.6s | 7,307 |
| extra-8-valuation-nvda-pe | valuation | NVDA trailing P/E (reworded) | `get_valuation` | PASS | 23.1s | 6,666 |
| extra-9-insider-msft | insider | Recent MSFT insider buy/sell activity | `get_insider_activity` | PASS | 11.4s | 6,900 |
| extra-10-risk-diff-aapl-reworded | filing text | AAPL risk-factor changes (reworded) | `diff_risk_factors` | PASS | 22.3s | 9,892 |
| extra-11-non-universe-tesla | out-of-scope decline | Tesla's margin (not tracked) | — | PASS | 24.0s | 4,065 |
| extra-12-forward-looking-aapl | out-of-scope decline | AAPL revenue next year | — | PASS | 12.3s | 3,893 |
| extra-13-nvda-mdna-themes | filing text | Main themes in NVDA's MD&A | `search_filings` | PASS | 27.9s | 8,562 |
| extra-14-ambiguous-risk-metric | clarification | "what's the most risk metric?" | — | PASS | 11.7s | 3,970 |
| extra-15-capex-intensity-msft-vs-aapl | comparative (own metric) | MSFT vs. AAPL capex intensity | `compare_companies` | PASS | 20.2s | 7,528 |

Each row also checks citation completeness (every stated figure traces to a `fundamental`,
`price`, `filing`, or `insider` source) and, where applicable, fiscal-year labeling in the answer
text — see `evals/run.py` for the full per-case assertion semantics.

**Why this matters — prior run vs. this one:** the previous committed run (see git history) scored
**8/15, brief 3/6**, run sequentially with a delay between questions. Two agent-loop fixes closed
that gap:
- `_finalize`'s citation-completeness retry only checked for `filing` citations — it now also
  checks `fundamental` and `price`, which was the root cause of 5 of the 7 prior failures
  (`brief-3`, `brief-4`, `extra-8`, `extra-10`, `extra-13`, all of which failed only on citations).
- The OpenAI client had no retry on transient errors (`max_retries=0`), so a single rate limit or
  connection blip failed the whole request. A deadline-aware single retry for
  `RateLimitError`/`APIConnectionError`/`APITimeoutError`/`InternalServerError` now recovers from
  these — validated by this run firing all 15 questions **fully concurrently** (the load pattern
  that previously caused 3/20 outright failures in isolated testing) with zero errors.

## Architecture

```
  SEC EDGAR (XBRL, filings, Form 4)        Yahoo Finance (prices, stooq fallback)
                    │                                     │
                    └─────────────────┬───────────────────┘
                                       ▼
                       ingestion/   only outbound HTTP; bronze-caches every
                                    raw response; --from-cache replays offline
                                       │
                                       ▼
                       PostgreSQL 16  committed pg_dump (seed/init/) auto-
                                      restores on first boot — cold clone,
                                      zero live calls
                                       │
                                       ▼
                       services/    pure, typed; no HTTP, no LLM
                          │                              │
                          ▼                              ▼
                api/ (FastAPI)               agent/ (openai SDK tool loop,
                GET /api/… — frozen           7 tools over the same services)
                contracts                         │ POST /api/ask
                          │                        │
                          └───────────┬────────────┘
                                      ▼
                frontend/  React 18 + Vite + TS, built to static files,
                           served by FastAPI in the packaged container
```

Full writeup, including the cross-source P/E join, fiscal-alignment rules, and the deliberate cuts:
**[docs/DESIGN.md](docs/DESIGN.md)**.

## Make targets

| Target | Purpose |
|--------|---------|
| `make setup` | Install backend deps into the uv-managed venv |
| `make web-setup` | Install frontend deps (Node 20) |
| `make db-up` / `make db-down` | Start/stop the Postgres dev database |
| `make init-db` | Create all tables against `DATABASE_URL` (idempotent) |
| `make run` | Serve the API with reload |
| `make test` / `make test-all` | Unit tests only / full suite incl. integration (needs Postgres) |
| `make verify` | Format + lint + types + coverage gates, then the frontend gate — must be green before any commit |
| `make evals` | Run the eval question set against a running `/api/ask` (needs a live LLM key) |
| `make cache-risk-themes` | Precompute + cache Item 1A risk themes for the tracked universe |
| `make seed-dump` | Dump the dev DB to `seed/init/` (auto-restored on a fresh clone) |
| `make fresh-check` | Fresh-clone rehearsal: clone, `docker compose up`, `/health`, `/api/companies`, one `/api/ask` |
