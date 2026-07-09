# Eval run — 2026-07-09T16:20:33+00:00

- Model: `unknown`   Base URL: `http://localhost:8000`
- Result: **12/14** passed · brief **5/6**

| ID | Question | Tools | T | Decl | Cite | Rgx | Lat(s) | Tokens | Result |
|----|----------|-------|---|------|------|-----|--------|--------|--------|
| brief-1-fundamentals | What were NVDA's revenue and net income for the last three fiscal years? | get_fundamentals | ✓ | ✓ | ✓ | – | 26.18 | 7970 | PASS |
| brief-2-compare-gross-margin | Which of the five companies had the highest gross margin last year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 12.47 | 7118 | PASS |
| brief-3-valuation-aapl-pe | What is AAPL's trailing P/E right now? | get_valuation | ✓ | ✓ | ✓ | – | 12.10 | 6329 | PASS |
| brief-4-risk-diff-nvda | What new risk factors did NVDA add in its latest 10-K versus the prior year? | diff_risk_factors | ✓ | ✗ | ✗ | – | 41.17 | 6336 | FAIL |
| brief-5-msft-revenue-and-mdna | How did MSFT's revenue grow last year, and what did management attribute it to? | get_fundamentals,search_filings | ✓ | ✓ | ✓ | – | 38.69 | 10655 | PASS |
| brief-6-forward-guidance-declined | What is the company's forward guidance for next quarter? | - | – | ✓ | – | – | 16.97 | 3830 | PASS |
| extra-7-compare-gross-margin-reworded | Across the tracked companies, whose gross margin was widest in its most recent fiscal year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 24.91 | 7586 | PASS |
| extra-8-valuation-nvda-pe | What is NVDA's trailing price-to-earnings ratio at the moment? | get_valuation | ✓ | ✓ | ✓ | – | 11.54 | 6387 | PASS |
| extra-9-insider-msft | What has MSFT insider buying and selling looked like recently? | get_insider_activity | ✓ | ✓ | ✓ | – | 14.59 | 6747 | PASS |
| extra-10-risk-diff-aapl-reworded | How did AAPL's risk factor disclosures change between its two most recent 10-K filings? | diff_risk_factors | ✓ | ✓ | ✓ | – | 32.18 | 9936 | PASS |
| extra-11-non-universe-tesla | What is Tesla's margin? | - | – | ✗ | – | – | 6.84 | 3861 | FAIL |
| extra-12-forward-looking-aapl | Where will AAPL revenue be next year? | - | – | ✓ | – | – | 10.18 | 3719 | PASS |
| extra-13-nvda-mdna-themes | What are the main themes in NVDA's MD&A? | search_filings,search_filings,search_filings | ✓ | ✓ | ✓ | – | 35.98 | 15281 | PASS |
| extra-14-ambiguous-risk-metric | what's the most risk metric? | - | – | ✓ | – | – | 5.65 | 3713 | PASS |

Tokens = prompt+completion summed across every LLM call of the request (from the X-Tracker-*-Tokens response headers); `n/a` means the provider omitted usage. Latency is client-side wall-clock. T=tools, Decl=declined/kind/followups, Cite=citation source types + items, Rgx=answer_regex; ✓ pass, ✗ fail, – not asserted.

_Committed as P9 evidence. Regenerate with `make evals`; do not edit by hand._
