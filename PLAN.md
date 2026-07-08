# Fundamentals Tracker — planning document

Planning output produced with Claude Code before implementation, committed as-is per the brief's deliverable list. Decisions were made in dialogue: locked choices I brought in, challenges the model raised (several backed by live EDGAR verification during planning), and how each was resolved are in the decision log (§12).

## 1. Problem and user

The user is a fundamental PM/analyst covering NVDA, MSFT, AAPL, GOOGL and ETN who wants one screen that answers: what did the company report, how is it trending, what is the market paying for it, and what changed in the filing narrative — without opening EDGAR. The universe is configuration (a settings list resolved to CIKs from `company_tickers.json` at ingest time), not code; swapping a ticker is a config edit plus a re-ingest.

The brief's six example questions are the acceptance tests, and the same questions anchor the committed eval set (§11):

| # | Question | Route | Correct behaviour |
|---|----------|-------|-------------------|
| 1 | NVDA revenue and net income, last three FYs | structured | 3 labelled FY rows, cited to accessions |
| 2 | Highest gross margin last year, of the five | derived, comparative | per-company latest reported FY resolved by the service, labels exposing that "last year" differs per company |
| 3 | AAPL trailing P/E right now | cross-source join | latest stored close ÷ latest reported-FY diluted EPS, both "as of" dates stated |
| 4 | New NVDA risk factors vs prior year | filing text | deterministic Item 1A diff, summarised, cited to both filings |
| 5 | MSFT revenue growth + management's attribution | cross-modal | XBRL YoY number + MD&A retrieval, both cited |
| 6 | Forward guidance for next quarter | out of scope | declined with reason — the tracker holds reported historicals only |

Non-goals, enforced by the agent's refusal policy: forecasts, price targets, investment advice, tickers outside the configured universe.

## 2. Architecture

```
   SEC EDGAR XBRL        SEC EDGAR filings          Yahoo Finance
   (companyfacts)     (submissions, 10-K HTML,     (daily OHLCV;
                            Form 4 XML)             stooq fallback)
         │                     │                         │
         └──────────┬──────────┴─────────────────────────┘
                    ▼
   ingestion/   — the ONLY module with outbound HTTP; one shared EDGAR client
                  (SEC_USER_AGENT header, ≤8 req/s global throttle, backoff
                  retries); every raw response bronze-cached to seed/bronze/
                    │            ▲
                    │            └── --from-cache replays the whole pipeline
                    ▼                offline from the bronze files
   PostgreSQL 16 — companies · fundamentals · prices · filings ·
                   filing_chunks (tsvector) · insider_transactions
                   committed pg_dump (seed/init/) auto-restores on first boot:
                   a cold clone serves real data with zero live API calls
                    │ reads
                    ▼
   services/    — pure typed functions: fundamentals, metrics, valuation,
                  compare, riskdiff, insider, retrieval. No HTTP, no LLM.
                    │                                │
                    ▼                                ▼
   api/ (FastAPI REST)                    agent/ (openai SDK tool loop;
   GET /api/…  ← frozen contracts         7 tools calling the same services)
                    │                                │ POST /api/ask
                    └────────────┬───────────────────┘
                                 ▼
   frontend/  — React 18 + Vite + TS strict + Tailwind + shadcn/ui + Recharts,
                built to static files, served by FastAPI; talks only to /api
```

Where the LLM **is**: routing a question to tools, composing cross-modal answers, summarising retrieved narrative and diff output, producing the final structured answer. Where it is **not**: it never issues HTTP or SQL, never computes or transforms a number (all metrics live in `services/` and are unit-tested), and is nowhere in the dashboard render path — every figure a user sees, in a panel or an answer, originates from a deterministic tool result.

## 3. Data model

All money values NUMERIC (never float), datetimes timezone-aware, one row = one fact with provenance. Canonical concepts are an enum defined once: `revenue, net_income, eps_diluted, gross_profit, cost_of_revenue, operating_income, cfo, capex, shares_diluted`. Expected volumes are small (≈250–350 fundamentals rows, ~2,500 price rows, low-hundreds to ~2k chunks, ≤200 insider rows) — index choices below are about correctness of access paths, not scale.

| Table | Columns | Keys / indexes |
|-------|---------|----------------|
| companies | cik int PK · ticker text UNIQUE · name text | — |
| fundamentals | id PK · cik FK · concept text · source_tag text · fiscal_year int · period_start date? · period_end date · value numeric · unit text · **accession text · filed date · form text** · superseded_value numeric? · superseded_filed date? | UNIQUE(cik, concept, fiscal_year, period_end); idx (cik, concept, fiscal_year) |
| prices | id PK · cik FK · date · open/high/low/close numeric · volume bigint · source text (yfinance/stooq) | UNIQUE(cik, date) |
| filings | accession text PK · cik FK · form text · fiscal_year int · period_end date · filed date · primary_doc_url text | — (feeds price-chart 10-K markers and citation URLs) |
| filing_chunks | id PK · accession FK · cik int · item text (1A/7/FULL) · fiscal_year int · chunk_index int · text text · tsv tsvector GENERATED (STORED) | UNIQUE(accession, item, chunk_index); GIN(tsv) |
| insider_transactions | id PK · cik FK · accession text · filed date · insider_name text · role text? · code text (P/S) · shares numeric · price numeric? · value numeric? | UNIQUE(accession, insider_name, code, shares, filed) |

Provenance (bold) rides on every fundamental row: which accession reported the surviving value, filed when, from which form and us-gaap tag (`source_tag`, admitting `derived:…` and `|split-adjusted` markers). `superseded_value`/`superseded_filed` keep restatements *visible*: when latest-filed-wins replaces a fact, the replaced value is retained so the UI can tooltip "restated — originally 11.93, filed 2024-02-21" and the agent can say so. `unit` is validated per concept at ingest (USD vs USD/shares vs shares) — a unit mixup would silently corrupt P/E. The tsvector column is Postgres-only; models guard it behind a dialect check so the unit suite runs on SQLite.

## 4. Source integration and the cross-source join

**EDGAR XBRL (structured backbone).** Resolve tickers → CIKs from `company_tickers.json`; pull `companyfacts` per CIK. Annual-fact selection: `form == "10-K"` (excludes 10-K/A; amendments arrive via latest-filed-wins anyway), `fp == "FY"`, and for duration concepts 330–400 days — verified necessary: 10-Ks carry quarterly facts marked `fp=FY`, and the surviving durations are exactly 363–370 days (52/53-week filers) and 364–365.

**Tag fallback chains, resolved per fiscal year.** Each concept has an ordered chain, e.g. revenue: `RevenueFromContractWithCustomerExcludingAssessedTax → Revenues → SalesRevenueNet`. Planning verification showed the chain must be evaluated **per (company, fiscal year)**, not per company: GOOGL reported contract revenue through FY2024 then switched to bare `Revenues` for FY2025 ($402.8B lives only there) — a company-level "first tag with data" pick would silently drop GOOGL's latest year. Facts are collected from all chain tags, then per year the highest-priority tag that has that year wins. Two derivations, both provenance-tagged and both *required* by the data: gross profit = revenue − cost_of_revenue (neither GOOGL nor ETN tags `GrossProfit`); operating income for ETN, which stopped tagging `OperatingIncomeLoss` after FY2019 — fallback `revenue − cost_of_revenue − SG&A − R&D`, with None-plus-reason when components are missing. Derived rows carry `source_tag="derived:…"` and the accession of the latest-filed input.

**Fiscal-year assignment — a verified trap.** EDGAR's `fy`/`fp` describe *the report a fact appeared in*, not the fact's period: AAPL's revenue for the year ending 2022-09-24 appears with fy=2022, 2023 **and** 2024 across successive 10-Ks. Trusting `fy` plus latest-filed-wins would label three different AAPL years all "FY2025". Two candidate fixes were tested against live data; the first (`min(fy)` per `(concept, end)` group) fails on older filings with filer-mislabeled `fy` and on periods predating a tag's XBRL history. Rule adopted: **fiscal_year = calendar year of period_end** — verified to match each of the five companies' own FY labels, including NVDA's late-January year-end (FY2026 ended 2026-01-25). Guardrails at ingest: for anchor facts (`end` == the filing's `reportDate`) the derived label is cross-checked against the filing's `fy`, fiscal years must be strictly increasing by period_end, and a per-ticker label offset exists in config for a future company whose convention differs. Violations log loudly; nothing loads silently mislabeled.

**EDGAR narrative.** From `submissions` (`recent.form/accessionNumber/primaryDocument/filingDate/reportDate` — shape verified), take the two most recent 10-Ks per company; `fiscal_year = year(reportDate)`. Fetch the primary document, strip HTML, extract Items 1A and 7 by regex boundaries, collecting all candidate spans and keeping the last/longest — the first match is the table of contents (AAPL's latest 10-K has 5 occurrences of "Item 1A": ToC, section header, cross-references). Extraction under 2,000 chars → whole-document chunks tagged `item=FULL` plus a warning (the brief explicitly allows full-text retrieval as fallback).

**Form 4.** From the same submissions payload: form == "4", last 12 months, cap 40/company. Verified wrinkle: `primaryDocument` is an XSL-rendered wrapper path (`xslF345X06/wk-form4_….xml`) — strip the directory prefix to fetch the raw XML (`<ownershipDocument>` with `nonDerivativeTransaction` elements). Keep transaction codes P and S only (the sample pulled during planning was a G — gift — which correctly drops); malformed XML logs and skips.

**Prices.** yfinance, 2 years daily, `auto_adjust=True` (split/dividend-adjusted — matters for the P/E join, §5); any failure falls to stooq's CSV endpoint behind the same interface, with `prices.source` recording which. "Latest close" is defined as the max stored trading date — at review time that is the seed's date, and every valuation surface labels it explicitly rather than implying "today".

**The cross-source join.** Trailing P/E = `close(max date)` ÷ `eps_diluted(latest reported FY)`, joined through ticker → CIK. The valuation payload carries both bases — `price_as_of` and the EPS row's `(fiscal_year, period_end, accession)` — so the UI and citations render "P/E 54.3× (FY2025 EPS, ended 27 Sep 2025 · price as of 3 Jul 2026)". Trailing P/S = price ÷ (revenue ÷ diluted WAD shares) on the same basis. Undefined cases (EPS ≤ 0) return None with a reason, rendered as "n.m. — negative EPS", never a crash or a fake number.

**Offline guarantee.** Every raw response (JSON, HTML, XML, CSV) lands in `seed/bronze/`; `--from-cache` replays the full pipeline with zero network. Separately, the committed `pg_dump` auto-restores via `docker-entrypoint-initdb.d`, so `docker compose up` on a cold clone serves real data without touching a live API. Both paths are rehearsed before submission (§11).

## 5. Fiscal alignment and restatement policy

The five companies' fiscal calendars are deliberately misaligned — this is surfaced, never hidden:

| Company | FY ends | Latest reported FY at plan time |
|---------|---------|--------------------------------|
| NVDA | ~last Sunday of January | FY2026 (ended 2026-01-25, filed 2026-02-25) |
| MSFT | June 30 | FY2025 (ended 2025-06-30) — FY2026 ended days ago, 10-K not yet filed |
| AAPL | last Saturday of September | FY2025 (ended 2025-09-27) |
| GOOGL | December 31 | FY2025 (ended 2025-12-31) |
| ETN | December 31 | FY2025 (ended 2025-12-31) |

Year-ends are read from data, never hardcoded. "Last year" in any cross-company context means **each company's latest reported FY** — the most recent fiscal year with a filed 10-K, not the most recent completed one (MSFT's FY2026 is complete but unreported, so its basis stays FY2025). This resolution happens in the compare *service*, not in the model (§7). Every user-facing value carries `fiscal_year + period_end` rendered as "FY2025 (ended 27 Sep 2025)"; comparative answers must state each company's label.

**Restatements: latest-filed-wins, kept visible.** Duplicate `(concept, period_end)` facts resolve to the latest-filed value; the replaced value is retained in `superseded_value/superseded_filed` so restatement handling is inspectable in the UI and citable by the agent, not just a code comment.

**Splits.** NVDA's 10:1 split (June 2024) is the live test case, and planning verification exposed a subtlety: newer filings restate comparative EPS post-split (FY2024: 11.93 in the FY2024 10-K → 1.19 in later filings), so latest-filed-wins is split-consistent — but only for years inside the newest filings' three-year comparative window. NVDA FY2022 EPS survives as pre-split 3.85 (adjusted ≈ 0.39) because that year fell out of the window before the split. Ingestion therefore detects per-share discontinuities (shares_diluted year-over-year ratio ≥ 1.5 → inferred split factor), back-adjusts older per-share facts deterministically (EPS ÷ factor, shares × factor, `source_tag += "|split-adjusted"`), and a named regression test pins NVDA's full EPS series. Prices are already split-adjusted (`auto_adjust=True`), so P/E never mixes bases; trailing multiples additionally only ever use the latest FY, which is always in-window.

## 6. Metrics catalogue

| Metric | Formula | Guards |
|--------|---------|--------|
| Revenue, net income, diluted EPS | reported (EPS split-adjusted per §5) | — |
| Gross margin | gross_profit ÷ revenue | GP derived for GOOGL, ETN; None if revenue missing |
| Operating margin | operating_income ÷ revenue | op income derived for ETN post-FY2019; None + reason if components missing |
| YoY growth (any concept) | x_t ÷ x_{t−1} − 1 | None if prior FY missing; None + "sign change / non-positive base" if x_{t−1} ≤ 0 |
| Trailing P/E | close(max date) ÷ EPS(latest reported FY) | None + "n.m. — negative EPS" if EPS ≤ 0; both dates always labelled |
| Trailing P/S | close ÷ (revenue ÷ diluted WAD shares) | None if inputs missing; share-basis caveat documented |
| FCF; FCF margin | CFO − capex; FCF ÷ revenue | None if either input missing |
| **FCF conversion** (own) | FCF ÷ net income | None + "undefined — net income ≤ 0" |
| **Operating leverage** (own) | ΔOpInc ÷ ΔRevenue, FY over FY | None + "n.m." if revenue fell, if abs(ΔRevenue) < 1% of revenue (denominator blow-up), or if OpInc changed sign |

**Why FCF conversion (earnings quality).** Accrual earnings and cash earnings diverge — through stock-based comp, working-capital swings, and capex cycles. Conversion near or above 1.0 says reported profit is turning into cash; a sagging ratio flags earnings quality deteriorating before the income statement shows it. Across this universe it separates asset-light software economics (MSFT, GOOGL) from a hardware cycle (NVDA's working-capital build) and an industrial (ETN).

**Why operating leverage (incremental margin).** ΔOpInc ÷ ΔRevenue tells an investor how much of each new revenue dollar reaches operating income — whether margin expansion is scale (incremental margin above average margin, as with NVDA's data-center ramp) or cost-cutting, and whether an industrial like ETN converts backlog into profitable growth. It is the trajectory metric a static margin table hides, and it needs only concepts already ingested.

Both are visualised (per-FY bars/lines on the Overview tab) and exposed to the agent via `get_fundamentals` and `compare_companies`.

## 7. Agent design

Hand-rolled tool-calling loop on the `openai` SDK, Chat Completions with `base_url` override — the interface every proxy and alternative provider implements; the graders point their proxy at it by setting three env vars. No agent framework: the graded behaviour — routing — should be legible in one file.

| Tool | Args | Returns | Backing service |
|------|------|---------|-----------------|
| get_fundamentals | ticker, concepts?, last_n_years? | per-FY rows: label, values, YoY, restatement notes | services.fundamentals + metrics |
| compare_companies | metric (basis is always latest reported FY, resolved server-side) | per-company {ticker, FY label, value} + machine-generated basis note the model must include | services.compare |
| get_valuation | ticker | P/E, P/S, price_as_of, EPS provenance, None-reasons | services.valuation |
| search_filings | ticker, query, item?, fiscal_year? | top-8 chunks: snippet, item, FY, accession, SEC URL | services.retrieval |
| diff_risk_factors | ticker | added[]/removed[] paragraph excerpts, counts, FY pair | services.riskdiff |
| get_insider_activity | ticker | 90d/365d buy/sell counts, net notional, 10b5-1 caveat line | services.insider |
| list_universe | — | tickers, names, latest reported FY each | services.fundamentals |

Every tool: a Pydantic v2 args model (the OpenAI tool JSON schema is generated from it — no hand-written schemas, kept flat for proxy compatibility), a handler calling the *same* service functions the REST API uses, and a compact return that always includes fiscal labels and provenance. Grounding is structural: the model cannot cite what it never received.

**Loop policy (every branch unit-tested against a scripted fake client).** Cap: 5 assistant turns / 8 tool executions; on cap-hit, force the final answer from accumulated results. Unknown tool or args failing validation → error returned as the tool result once; repeat failure → declined FinalAnswer. Search returning nothing → the tool description instructs reformulation (fewer terms, synonyms), budget 3 search calls. Model finishing in plain text → one nudge toward the structured final; then wrap as best-effort. Hard 30s request timeout mapped to a clean API error; the OpenAI client runs off the event loop so a slow question never freezes the dashboard. `/api/ask` never 500s on model misbehaviour.

**Structured final answer — transport ladder** (unknown proxy capabilities are the top review-time risk): try `response_format: json_schema` bound to `FinalAnswer{answer_md, citations[], trace[], declined, decline_reason}`; on rejection fall back to a `final_answer` *tool call* carrying the same schema (tool calling must work for the agent to exist at all, so it is the reliable channel); last resort, `json_object` + schema-in-prompt with Pydantic validate-and-retry-once. Capability detected once at startup and logged; `make evals` re-pointed at a second provider proves the ladder before submission.

**Grounding and refusal.** System-prompt rules: answer only from tool results; every number cites (FY + accession), every narrative claim cites (form, FY, item); cross-company answers must state each company's FY label; when a metric comes back None-with-reason, relay the reason — never improvise a number. Declined categories: forward-looking (guidance, forecasts, targets), non-universe tickers, investment advice — each with `decline_reason`. One rule is also enforced in code: an answer containing digits with an empty citations list triggers one corrective retry.

**Trace.** Every answer returns its tool trace `{tool, args, result_summary}`, rendered in the UI as a collapsed "How I answered" accordion — the routing behaviour the brief grades is inspectable question by question.

## 8. Retrieval design

Corpus: 2 fiscal years × 5 companies × 2 items ≈ 20 sections, chunked to ~1,400 chars with 200 overlap at paragraph boundaries — low hundreds to ~2k chunks (AAPL's stripped 10-K is ~226k chars total, and Items 1A + 7 are a fraction of that). Retrieval is Postgres FTS: stored generated tsvector, GIN index, `websearch_to_tsquery`, `ts_rank` ordering, `ts_headline` snippets, filtered by (cik, item, fiscal_year).

Why not embeddings: (a) at this corpus size, ranking-quality differences are noise; (b) the searcher is the agent, which reformulates a failed query mid-loop — a luxury a human searcher doesn't get; (c) an embedding model is a second model dependency behind an unknown review-time proxy, and pgvector another moving part in compose; (d) FTS ranking is deterministic and explainable in an eval. The honest failure mode: `websearch_to_tsquery` ANDs terms, so a paraphrase ("supply constraints" vs "capacity limitations") can return zero rows. Mitigations: the tool description mandates reformulation with fewer/alternate terms (3-call budget), item filters shrink the haystack, two paraphrase questions sit in the eval set, and the flagship narrative question (new risk factors) is served by the deterministic diff tool, not retrieval. Unit tests run on SQLite behind the same interface (ILIKE); FTS ranking/filter/snippet behaviour is covered in the Postgres integration job so the path the agent actually uses is tested.

**Risk-factor diff (the non-retrieval narrative path).** Paragraphs are matched by best `SequenceMatcher` ratio (threshold ≈ 0.6–0.75, tuned on the real NVDA pair *before* the UI card is built), not positionally — year-over-year 10-Ks reorder and reflow, and positional diffing degenerates into "everything changed". Output: added/removed paragraph excerpts capped top-N by length; the LLM only summarises this output.

## 9. UI: layout and components

`.claude/skills/dashboard-design/SKILL.md` (committed) is the design authority — dark "quiet terminal" theme, one accent, contrast ≥ 4.5:1 as a review-blocking rule, tabular-nums right-aligned numerals, fiscal labels on every value.

```
┌ sidebar 232px ┬ top bar: name+ticker · FY chip · trailing P/E ·─┬ Q&A sheet 400px ┐
│ product name  │          freshness · [Ask]                      │ example chips    │
│ 5 companies   ├ Tabs: Overview | Compare ───────────────────────┤ thread           │
│ (ticker, muted│ KPI row: Revenue · Net income · Gross margin ·  │ citation pills   │
│  name, FY     │          Operating margin · FCF margin          │ trace accordion  │
│  badge)       │ fundamentals table 7/12 · price chart 5/12      │ declined state   │
│ freshness ftr │ earnings-quality · op-leverage · insider ·      │                  │
│               │ risk-diff cards                                 │                  │
└───────────────┴─────────────────────────────────────────────────┴──────────────────┘
```

| Component | Endpoint | Notes |
|-----------|----------|-------|
| Sidebar selector | /api/companies (+fundamentals) | latest-FY badge per company — fiscal misalignment visible before any chart |
| KPI row (5 cards) | /companies/{t}/fundamentals | YoY delta chips: arrow + sign, never colour alone; FY sublabel |
| Fundamentals table | same | columns = last 4 FYs, two-line headers "FY2025 / ended 27 Sep 2025", YoY column; em dash + tooltip reason for None; restated values tooltip the superseded figure |
| Price chart | /companies/{t}/prices + /filings | range control; 10-K filing-date reference markers (from the filings table) |
| Earnings quality card | fundamentals | FCF margin bars + conversion line per FY |
| Operating leverage card | fundamentals | ΔOpInc vs ΔRev, ratio labelled, n.m. states |
| Insider card | /companies/{t}/insider | 90d/365d buys vs sells + net notional; one-line 10b5-1 caveat; deliberate empty state |
| Risk-diff card | /companies/{t}/risk-diff | added/removed counts, expandable excerpts, SEC link-out |
| Compare tab | /api/compare?metric=… | grouped bars, fixed per-ticker colours, each bar footnoted with its own FY label; caption "Basis: latest reported fiscal year per company" |
| Q&A sheet | POST /api/ask | slide-over so data stays visible; chips seed the brief's question types; citation pills link to SEC; trace accordion; declined ≠ error styling |

Every remote panel has skeleton/empty/error states. The freshness footer shows max price date and max filed date from the seed — never "today".

## 10. Build plan

Ten chunks, each ending green (`make verify` = format, lint, mypy, unit tests + coverage gate), reviewed, and merged before dependents start. Lanes: foundation → {ingestion, backend, frontend} in parallel → agent → packaging. Acceptance criteria use values verified during planning.

| # | Chunk | Acceptance criteria |
|---|-------|---------------------|
| 1 | Foundation: uv project, ruff/mypy/pytest, full schema, frozen API contracts, /health, compose db, CI, Makefile | make verify green; init_db idempotent; /health 200; CI green |
| 2 | XBRL ingestion: shared EDGAR client (UA, throttle, retries, bronze cache), per-FY tag-chain resolution, fiscal-year rule, dedupe + superseded capture, GP/OpInc derivations, split adjustment | 5 tickers × ≥4 FYs; latest FYs = §5 table; GOOGL FY2025 revenue ≈ $402.8B via `Revenues`; ETN operating margin present via derivation; NVDA FY2024 EPS = 1.19 (not 11.93) and FY2022 split-adjusted; --from-cache rerun: zero network, identical counts |
| 3 | Narratives + Form 4 + prices + seed: item extraction (ToC dodge, FULL fallback), chunker, Form 4 XML (XSL-prefix strip), yfinance→stooq, pg_dump seed | Items 1A+7 × 2 FYs × 5 companies (≤1 FULL fallback); ~500 price rows/ticker; `compose down -v && up` restores from seed alone; NVDA "export controls" FTS query returns chunks |
| 4 | Metrics engine: the seven service modules, all None-with-reason guards | services ≥90% covered; one P/E recomputed by hand matches |
| 5 | API: 8 read endpoints + freshness, 404/422 paths, integration tests | /docs clean; valuation exposes both as-of dates + provenance; compare exposes per-company FY labels |
| 6 | Frontend foundation: tokens → Tailwind, types generated from OpenAPI, shell, async states | live sidebar + FY badges; tsc + build green; bundle < 1 MB gz |
| 7 | Data panels: KPI row, table, price chart + markers, 4 analytical cards, Compare tab | 3 values cross-checked against raw API; NVDA↔MSFT switch shows different period-end headers |
| 8 | Agent: llm client + capability probe, 7 tools, prompt, loop, /api/ask, fake-client tests | brief Q1 routes to get_fundamentals only; Q5 uses fundamentals + search_filings; Q6 declines; every loop-policy branch tested; agent ≥85% covered |
| 9 | Q&A UI + evals: sheet wiring, citation pills, trace accordion, declined style; 12-question runner + committed results | ≥11/12 pass, all 6 brief questions pass; second-provider run recorded |
| 10 | Packaging: multi-stage Dockerfile, compose app service, run.sh, README, design writeup, fresh-clone rehearsal | cold `docker compose up --build` serves dashboard from seed only; fresh-clone script passes end-to-end incl. one /api/ask |

If time runs short, the pre-agreed cut order is: Windows CI leg → insider chart (table stays) → second Compare chart → 4 of 12 eval questions. Never cut: seed snapshot, citations, trace, refusal, fresh-clone rehearsal.

## 11. Testing and CI strategy

| Layer | Runs on | What it proves |
|-------|---------|----------------|
| Unit (no network, SQLite) | every push, 3 OS | fact selection on committed companyfacts-shaped fixtures — named regression tests for every verified trap: `test_comparative_year_not_mislabeled` (fy-field bug), `test_googl_revenue_tag_switch`, `test_etn_operating_income_derived`, `test_nvda_split_series_consistent`, `test_toc_span_skipped`; duration filter; superseded capture; chunker properties; Form 4 XML incl. missing price; metric guards (negative EPS, sign flips, tiny ΔRevenue); agent loop on a scripted fake client: routing, refusal, schema-retry, citation-retry, arg-error recovery, plain-text nudge, cap-hit, trace order |
| Integration (Postgres service) | ubuntu CI job | FTS ranking/filters/snippets (the path the agent uses), every endpoint incl. error paths, seed restore |
| Evals (live LLM) | locally, results committed | the same 12 questions as §1 + additions; machine-checked per question: expected tools in trace, declined flags, citations non-empty and resolvable, numeric claims within tolerance of DB ground truth; run against two providers via env swap |
| Fresh-clone rehearsal | before submission | clone → compose up → /health → /api/companies → one /api/ask, from seed only, no prior volumes |

Coverage gate 80% on backend (services ≥90% — where correctness lives). CI never touches live EDGAR (etiquette + determinism); ingestion tests replay bronze fixtures. Evals stay out of CI (live key); CI validates the question-set structure instead.

## 12. Decision log

Entries marked ⚡ record pushback raised during planning; several were settled by live EDGAR verification rather than argument.

| # | Decision | Options | Chosen & why |
|---|----------|---------|--------------|
| 1 | ⚡ Persistence | SQLite(+FTS5) / CSV / Postgres | Postgres 16. Challenge raised: SQLite-FTS5 would make the committed seed a single file and unify the test dialect. Withdrawn because ts_rank/ts_headline feed the agent's citations, compose+pg_dump auto-restore keeps cold start at one command, and the brief names Postgres a bonus. Residual (FTS only tested in integration job) mitigated by putting retrieval tests there explicitly |
| 2 | Backend | Flask / Django / FastAPI | FastAPI: typed Pydantic contracts, OpenAPI feeds generated TS types, /docs for free |
| 3 | Frontend | Streamlit / Dash / React+Vite+TS | React: analyst-grade layout control, static build served by FastAPI = one container. Cost accepted: build pipeline |
| 4 | Agent orchestration | LangGraph / LiteLLM / hand-rolled | Hand-rolled ~100-line loop: routing must be gradeable by reading one file. (LangGraph is my production default; deliberately not here) |
| 5 | LLM protocol | Responses API / Chat Completions | Chat Completions + base_url override: what every proxy implements; review-time portability |
| 6 | ⚡ FinalAnswer transport | assume json_schema / degradation ladder | Unknown proxies reject `json_schema`, `strict`, `tool_choice:"required"`. Ladder: json_schema → `final_answer` tool call (tool calling must work anyway) → json_object + validate-and-retry. Startup capability probe, proven on two providers |
| 7 | ⚡ Retrieval | pgvector+embeddings / Postgres FTS | FTS: tiny corpus, agent reformulates in-loop, no second model dependency. Challenge recorded: AND-semantics paraphrase misses; mitigations §8 + two paraphrase eval questions |
| 8 | ⚡ fiscal_year source | trust EDGAR `fy` / min(fy) per period / year(period_end) | **Challenged, then revised twice on evidence.** `fy` is the report's year (AAPL FY2022 revenue carries fy=2022/2023/2024) — refuted. My first fix, min(fy) per (concept, end), also refuted: filer-mislabeled fy in NVDA's 2011–2014 filings and tag-history truncation. Adopted: year(period_end), verified against all five companies' own labels, anchor-fact cross-check + config override for generality |
| 9 | ⚡ Restatement policy | first-reported / latest-filed-wins / latest + superseded kept | Latest-filed-wins for values, but the replaced value is retained (superseded_value/filed) — otherwise restatement handling is invisible to a reviewer. Verified caveat drove a second change: NVDA's split restatement only covers the 3-year comparative window, so ingest also detects share-count discontinuities and back-adjusts older per-share facts (FY2022 EPS 3.85 → ≈0.39) |
| 10 | Trailing P/E basis | TTM from quarters / latest annual EPS | Annual (the brief's own example): quarterly XBRL selection doubles the messy-data surface. Staleness made honest instead: both as-of dates in every valuation surface ("FY2025 EPS, ended 30 Jun 2025 · price as of 3 Jul 2026") |
| 11 | ⚡ P/S share basis | dei cover-page shares / diluted WAD shares | WAD shares: same denominator family as EPS, split-consistent via §5, no second taxonomy. Accepted, unmitigated: understates buybacks by a few percent for AAPL-like repurchasers — documented in the tool output rather than fixed |
| 12 | Own metrics | ROIC / rule-of-40 / accruals ratio / chosen pair | FCF conversion + operating leverage: computable from concepts already ingested, complementary (earnings quality + margin trajectory), each explainable to a PM in one sentence |
| 13 | Bonus dataset | call transcripts / short interest / Form 4 | Form 4: SEC-native (same client, etiquette, cache), joins narrative to insider behaviour. Thin slice: 12 months, P/S codes, net summary — plus a 10b5-1 caveat on the card so the signal isn't oversold |
| 14 | Risk-factor diff | LLM-diff / positional difflib / similarity pairing + LLM summary | Deterministic similarity pairing (positional diff degenerates when filings reorder sections), tuned on the real NVDA pair before UI work; the LLM only summarises diff output |
| 15 | Evals in CI | yes / committed evidence | Out of CI (live key); committed last-run results + CI-safe structure test |
| 16 | ⚡ CI matrix | ubuntu-only / 3 OS | Challenged as gold-plating. Kept: mac/windows run the unit suite only (cheap, evidences pathlib discipline); explicitly first in the cut order |
| 17 | ⚡ ETN operating income | omit for ETN / derive from components | Discovered in planning verification: ETN stopped tagging OperatingIncomeLoss after FY2019. Derive revenue − COGS − SG&A − R&D with `derived:` provenance; None-with-reason if components missing. Omitting would hole two required metrics for one of five names |

## 13. Risks and mitigations

| Risk | Detection / mitigation |
|------|------------------------|
| yfinance breakage or schema drift (frequent) | stooq fallback behind the same interface, source column records which; validation at the boundary; committed seed means review never depends on it |
| Item 1A/7 extraction fails on one filing's HTML | ToC-dodge (last/longest span) + <2,000-char check → FULL fallback + warning; risk-diff card degrades to an explicit "extraction failed" state |
| Review-time proxy rejects structured output / strict tools | transport ladder (§7), flat tool schemas, capability probe, two-provider eval runs before submission |
| Tag drift on a swapped-in ticker | per-company × concept coverage report printed at end of every ingest run; missing cells are loud |
| SEC blocks scripted access | declared User-Agent, ≤8 req/s global throttle, backoff; full offline replay via bronze |
| Agent mislabels cross-company comparisons | basis resolved in the compare service, labels in every tool return, prompt requires stating them, eval asserts all five FY labels appear |
| Model invents numbers or drops citations | numbers exist only in tool results; code-level citation check with corrective retry; evals assert citations resolve |
| Split/restatement edge cases beyond NVDA | share-count discontinuity detection is generic; monotonic-FY and anchor-fact validations log loudly instead of loading bad labels |
| Insider signal misread (10b5-1 autopilot sales) | accepted: caveat line on card and in tool output; not presented as sentiment |
| Slow /api/ask blocks the dashboard | LLM calls off the event loop; 30s hard timeout → clean error state; no streaming (cut) |
| Time overrun (8–10h budget) | pre-agreed cut order (§10); the never-cut list protects the graded core |

## 14. Deliberate cuts

- **Streaming answers** — polish, not graded; the thinking indicator covers 20–60s latencies.
- **Auth/multi-user** — internal single-analyst prototype.
- **pgvector/embeddings** — §8; lexical FTS + agent reformulation covers a ~20-section corpus.
- **Alembic migrations** — schema ships once with a seed; create_all + pg_dump is honest for a prototype.
- **TTM P/E from quarterly XBRL** — decision log #10; annual basis with honest dual-date labels.
- **Point-in-time / as-first-reported view** — a real quant shop would want lookahead-safe history; latest-filed-wins loses it. The superseded columns and bronze cache keep the door open (decision log #9).
- **Forecasting/forward estimates** — out of scope by the brief; the refusal policy is the feature.
- **Quarterly fundamentals** — annual answers every acceptance question; quarters double alignment complexity.
- **Form 4 derivative tables** — nonDerivative P/S codes only; the rest is noise for this signal.
- **Extra tickers** — universe is config-driven and generalises (per-FY tag chains, fiscal-label validation), but the graded set stays fixed.
- **Light theme** — one audited dark theme beats two half-audited ones.
- **Live/intraday prices; response caching** — daily close is the valuation basis; freshness is labelled instead.
