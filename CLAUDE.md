# Fundamentals Tracker — project instructions

Case-study prototype for Schonfeld: a dashboard tracking SEC-filing fundamentals + market data for a small
configurable universe, with a grounded LLM Q&A layer. Graded on: engineering quality, time-series data
design (fiscal alignment, restatements), AI integration (routing, tool use, structured outputs, grounding,
refusal), dashboard quality, product judgment, scope discipline, communication. Optimise for those, in that
spirit: a working prototype with deliberate cuts, not a production system.

## Architecture (frozen — do not restructure without asking)
backend/src/tracker/
  config.py          pydantic-settings; ALL config from env
  db/                SQLAlchemy 2.0 models + session; natural-key uniques; provenance columns
  ingestion/         ONLY place that talks to the outside world (EDGAR, yfinance/stooq); writes DB;
                     bronze-caches every raw response under seed/bronze/; --from-cache replays offline
  services/          pure, typed business logic; reads DB; no HTTP out, no LLM; unit-testable on SQLite
  agent/             ONLY place that imports openai; tools call services/ functions directly
  api/               thin FastAPI routers over services/; contracts live in api/schemas.py and are frozen
frontend/            React 18 + Vite + TS strict + Tailwind + shadcn/ui + Recharts; talks only to /api
evals/               question set + runner hitting /api/ask; evidence committed as last_run.md
seed/                committed pg_dump (seed/init/) + bronze raw responses (seed/bronze/)

## Non-negotiables
- Python 3.12, uv, ruff (format+lint), mypy on backend/src, Pydantic v2 at every boundary.
- pathlib only (Windows CI runs the unit suite); timezone-aware datetimes.
- SEC etiquette: every EDGAR request sends the SEC_USER_AGENT header, global throttle <= 8 req/s,
  tenacity retries with backoff. Never bypass the shared edgar client.
- Fiscal policy: every fundamental carries fiscal_year + period_end; anything user-facing labels values as
  "FY2025 (ended 2025-09-27)"; cross-company "last year" = latest reported FY per company (latest
  filed 10-K, not merely completed); duplicate
  (concept, period) rows resolve latest-filed-wins, provenance (accession, filed) retained.
- Errors: no silent excepts; ingestion logs and skips bad records, never crashes a whole run; services
  return None-with-reason for undefined metrics (negative EPS P/E etc.) instead of raising.
- Comments explain WHY or flag a domain trap only. Never narrate what the code does. Docstrings on public
  functions: one line + formula/contract where relevant.
- Tests accompany every ingestion/services/agent module in the same chunk. Backend coverage gate: 80%.
- Frontend: .claude/skills/dashboard-design/SKILL.md is the design authority. Contrast >= 4.5:1 for all
  text; NEVER dark text on dark surfaces; tabular-nums on numbers; every remote panel has skeleton/empty/
  error states.
- Secrets only via env; .env is gitignored; committed data under seed/ is deliberate.

## Workflow
- Branch per lane (feat/foundation|ingestion|backend|frontend|agent). Conventional commits: lowercase,
  imperative, <= 60 chars, no ticket codes (feat|fix|test|docs|chore|refactor|ci). Small commits, one
  concern each — use /commit-batch.
- /verify (= make verify) must be green before ANY commit. Never loosen a config, threshold, or test to
  make it pass; fix the cause or ask.
- Before merging a lane: run the code-reviewer agent, fix BLOCKING items.
- Merge shape: git merge --no-ff feat/<lane> -m "merge: <lane> lane - <scope>". Never force-push.

## Environment
DATABASE_URL · LLM_BASE_URL · LLM_API_KEY · LLM_MODEL · SEC_USER_AGENT   (see .env.example)

## Definition of done, every task
make verify green · new logic tested · acceptance criteria of the current playbook chunk met · no stray
TODOs · user-visible values carry fiscal labels and provenance.
