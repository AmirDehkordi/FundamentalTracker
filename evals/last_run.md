# Eval run — 2026-07-09T11:23:08+00:00

- Model: `gpt-5.5`   Base URL: `http://localhost:8000`
- Result: **12/12** passed · brief **6/6**

| ID | Question | Tools | T | Decl | Cite | Rgx | Lat(s) | Tokens | Result |
|----|----------|-------|---|------|------|-----|--------|--------|--------|
| brief-1-fundamentals | What were NVDA's revenue and net income for the last three fiscal years? | get_fundamentals | ✓ | ✓ | ✓ | – | 14.65 | 6297 | PASS |
| brief-2-compare-gross-margin | Which of the five companies had the highest gross margin last year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 7.13 | 5367 | PASS |
| brief-3-valuation-aapl-pe | What is AAPL's trailing P/E right now? | get_valuation | ✓ | ✓ | ✓ | – | 6.39 | 4767 | PASS |
| brief-4-risk-diff-nvda | What new risk factors did NVDA add in its latest 10-K versus the prior year? | diff_risk_factors | ✓ | ✓ | ✓ | – | 18.57 | 7626 | PASS |
| brief-5-msft-revenue-and-mdna | How did MSFT's revenue grow last year, and what did management attribute it to? | get_fundamentals,search_filings | ✓ | ✓ | ✓ | – | 26.28 | 9469 | PASS |
| brief-6-forward-guidance-declined | What is the company's forward guidance for next quarter? | - | – | ✓ | – | – | 3.88 | 2711 | PASS |
| extra-7-compare-gross-margin-reworded | Across the tracked companies, whose gross margin was widest in its most recent fiscal year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 6.81 | 5231 | PASS |
| extra-8-valuation-nvda-pe | What is NVDA's trailing price-to-earnings ratio at the moment? | get_valuation | ✓ | ✓ | ✓ | – | 6.45 | 4861 | PASS |
| extra-9-insider-msft | What has MSFT insider buying and selling looked like recently? | get_insider_activity | ✓ | ✓ | ✓ | – | 8.66 | 5091 | PASS |
| extra-10-risk-diff-aapl-reworded | How did AAPL's risk factor disclosures change between its two most recent 10-K filings? | diff_risk_factors | ✓ | ✓ | ✓ | – | 22.21 | 7984 | PASS |
| extra-11-non-universe-tesla | What is Tesla's margin? | get_fundamentals | – | ✓ | – | – | 5.85 | 4455 | PASS |
| extra-12-forward-looking-aapl | Where will AAPL revenue be next year? | - | – | ✓ | – | – | 4.81 | 2640 | PASS |

Tokens = prompt+completion summed across every LLM call of the request (from the X-Tracker-*-Tokens response headers); `n/a` means the provider omitted usage. Latency is client-side wall-clock. T=tools, Decl=declined, Cite=citation source types, Rgx=answer_regex; ✓ pass, ✗ fail, – not asserted.

_Committed as P9 evidence. Regenerate with `make evals`; do not edit by hand._
