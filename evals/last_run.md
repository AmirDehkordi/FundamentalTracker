# Eval run — 2026-07-09T12:48:04+00:00

- Model: `gpt-5.5`   Base URL: `http://localhost:8000`
- Result: **12/12** passed · brief **6/6**

| ID | Question | Tools | T | Decl | Cite | Rgx | Lat(s) | Tokens | Result |
|----|----------|-------|---|------|------|-----|--------|--------|--------|
| brief-1-fundamentals | What were NVDA's revenue and net income for the last three fiscal years? | get_fundamentals | ✓ | ✓ | ✓ | – | 11.79 | 6032 | PASS |
| brief-2-compare-gross-margin | Which of the five companies had the highest gross margin last year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 8.01 | 5239 | PASS |
| brief-3-valuation-aapl-pe | What is AAPL's trailing P/E right now? | get_valuation | ✓ | ✓ | ✓ | – | 6.89 | 4739 | PASS |
| brief-4-risk-diff-nvda | What new risk factors did NVDA add in its latest 10-K versus the prior year? | diff_risk_factors | ✓ | ✓ | ✓ | – | 17.59 | 7663 | PASS |
| brief-5-msft-revenue-and-mdna | How did MSFT's revenue grow last year, and what did management attribute it to? | get_fundamentals,search_filings | ✓ | ✓ | ✓ | – | 18.88 | 6680 | PASS |
| brief-6-forward-guidance-declined | What is the company's forward guidance for next quarter? | - | – | ✓ | – | – | 6.15 | 2705 | PASS |
| extra-7-compare-gross-margin-reworded | Across the tracked companies, whose gross margin was widest in its most recent fiscal year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 13.02 | 5763 | PASS |
| extra-8-valuation-nvda-pe | What is NVDA's trailing price-to-earnings ratio at the moment? | get_valuation | ✓ | ✓ | ✓ | – | 9.12 | 4905 | PASS |
| extra-9-insider-msft | What has MSFT insider buying and selling looked like recently? | get_insider_activity | ✓ | ✓ | ✓ | – | 9.31 | 5119 | PASS |
| extra-10-risk-diff-aapl-reworded | How did AAPL's risk factor disclosures change between its two most recent 10-K filings? | diff_risk_factors | ✓ | ✓ | ✓ | – | 25.44 | 8146 | PASS |
| extra-11-non-universe-tesla | What is Tesla's margin? | get_fundamentals | – | ✓ | – | – | 6.52 | 4448 | PASS |
| extra-12-forward-looking-aapl | Where will AAPL revenue be next year? | - | – | ✓ | – | – | 4.17 | 2676 | PASS |

Tokens = prompt+completion summed across every LLM call of the request (from the X-Tracker-*-Tokens response headers); `n/a` means the provider omitted usage. Latency is client-side wall-clock. T=tools, Decl=declined, Cite=citation source types, Rgx=answer_regex; ✓ pass, ✗ fail, – not asserted.

_Committed as P9 evidence. Regenerate with `make evals`; do not edit by hand._
