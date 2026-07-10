# Eval run — 2026-07-10T02:24:05+00:00

- Model: `gpt-5.5`   Base URL: `http://localhost:8000`
- Result: **15/15** passed · brief **6/6**

| ID | Question | Tools | T | Decl | Cite | Rgx | Lat(s) | Tokens | Result |
|----|----------|-------|---|------|------|-----|--------|--------|--------|
| brief-1-fundamentals | What were NVDA's revenue and net income for the last three fiscal years? | get_fundamentals | ✓ | ✓ | ✓ | – | 15.99 | 7818 | PASS |
| brief-2-compare-gross-margin | Which of the five companies had the highest gross margin last year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 11.53 | 7237 | PASS |
| brief-3-valuation-aapl-pe | What is AAPL's trailing P/E right now? | get_valuation | ✓ | ✓ | ✓ | – | 6.43 | 6688 | PASS |
| brief-4-risk-diff-nvda | What new risk factors did NVDA add in its latest 10-K versus the prior year? | diff_risk_factors | ✓ | ✓ | ✓ | – | 24.94 | 10125 | PASS |
| brief-5-msft-revenue-and-mdna | How did MSFT's revenue grow last year, and what did management attribute it to? | get_fundamentals,search_filings | ✓ | ✓ | ✓ | – | 35.31 | 10865 | PASS |
| brief-6-forward-guidance-declined | What is the company's forward guidance for next quarter? | - | – | ✓ | – | – | 6.51 | 3972 | PASS |
| extra-7-compare-gross-margin-reworded | Across the tracked companies, whose gross margin was widest in its most recent fiscal year? | compare_companies | ✓ | ✓ | ✓ | ✓ | 10.57 | 7307 | PASS |
| extra-8-valuation-nvda-pe | What is NVDA's trailing price-to-earnings ratio at the moment? | get_valuation | ✓ | ✓ | ✓ | – | 23.06 | 6666 | PASS |
| extra-9-insider-msft | What has MSFT insider buying and selling looked like recently? | get_insider_activity | ✓ | ✓ | ✓ | – | 11.35 | 6900 | PASS |
| extra-10-risk-diff-aapl-reworded | How did AAPL's risk factor disclosures change between its two most recent 10-K filings? | diff_risk_factors | ✓ | ✓ | ✓ | – | 22.33 | 9892 | PASS |
| extra-11-non-universe-tesla | What is Tesla's margin? | - | – | ✓ | – | – | 23.97 | 4065 | PASS |
| extra-12-forward-looking-aapl | Where will AAPL revenue be next year? | - | – | ✓ | – | – | 12.33 | 3893 | PASS |
| extra-13-nvda-mdna-themes | What are the main themes in NVDA's MD&A? | search_filings | ✓ | ✓ | ✓ | – | 27.87 | 8562 | PASS |
| extra-14-ambiguous-risk-metric | what's the most risk metric? | - | – | ✓ | – | – | 11.73 | 3970 | PASS |
| extra-15-capex-intensity-msft-vs-aapl | How capital intensive is MSFT compared to AAPL? | compare_companies | ✓ | ✓ | ✓ | ✓ | 20.19 | 7528 | PASS |

Tokens = prompt+completion summed across every LLM call of the request (from the X-Tracker-*-Tokens response headers); `n/a` means the provider omitted usage. Latency is client-side wall-clock. T=tools, Decl=declined/kind/followups, Cite=citation source types + items, Rgx=answer_regex; ✓ pass, ✗ fail, – not asserted.

_Committed as P9 evidence. Regenerate with `make evals`; do not edit by hand._
