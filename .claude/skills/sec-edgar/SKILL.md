---
name: sec-edgar
description: Domain knowledge for ingesting SEC EDGAR data. Use for any work touching XBRL company facts, 10-K narrative extraction, Form 4 insider transactions, ticker/CIK mapping, fiscal-year alignment, restatements, or SEC request etiquette.
---

# SEC EDGAR domain guide

## Etiquette (mandatory)
Every request: header User-Agent = SEC_USER_AGENT env ("Name email (purpose)"). Global throttle <= 8 req/s
across all EDGAR endpoints. Retries: 3, exponential backoff, on 429/5xx/timeout. All raw responses cached to
seed/bronze/ so ingestion replays offline with --from-cache.

## Endpoints
Ticker->CIK map:  https://www.sec.gov/files/company_tickers.json   (CIK zero-padded to 10 digits in URLs)
Company facts:    https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
Submissions:      https://data.sec.gov/submissions/CIK{cik:010d}.json
Filing document:  https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{primaryDocument}
Never hardcode CIKs; resolve from the map. AAPL -> 320193 is a good sanity value only.

## Canonical concepts and us-gaap tag fallback chains (resolve PER (company, fiscal year))
For each year, the first tag in the chain having that year wins — never "first tag with any data" per
company: GOOGL reported contract revenue through FY2024 then switched to bare Revenues for FY2025
($402.8B lives only there); a company-level pick silently drops GOOGL's latest year.
revenue:          RevenueFromContractWithCustomerExcludingAssessedTax -> Revenues -> SalesRevenueNet
net_income:       NetIncomeLoss
eps_diluted:      EarningsPerShareDiluted            (units: USD/shares)
gross_profit:     GrossProfit -> derive revenue - cost_of_revenue (tag derived:...)
cost_of_revenue:  CostOfRevenue -> CostOfGoodsAndServicesSold
operating_income: OperatingIncomeLoss -> derive revenue - cost_of_revenue - sga - rnd
sga:              SellingGeneralAndAdministrativeExpense            (derivation input only)
rnd:              ResearchAndDevelopmentExpense                     (derivation input only)
cfo:              NetCashProvidedByUsedInOperatingActivities
capex:            PaymentsToAcquirePropertyPlantAndEquipment
shares_diluted:   WeightedAverageNumberOfDilutedSharesOutstanding   (units: shares)
Derivation is a designed-for path, not an exception: neither GOOGL nor ETN tags GrossProfit, and ETN
stopped tagging OperatingIncomeLoss after FY2019. Derived rows carry source_tag="derived:..." plus the
accession of the latest-filed input, and surface None-with-reason when a component is missing.

## Selecting annual facts (the messy-data core)
Keep entries where form == "10-K" (also excludes 10-K/A; amendments arrive via latest-filed-wins) AND
fp == "FY". For duration concepts require 330 <= (end-start).days <= 400 — verified necessary: 10-Ks carry
QUARTERLY facts marked fp=FY; surviving durations are exactly 363-370d (52/53-week filers) and 364-365d.
fiscal_year: NEVER trust the entry's "fy" — it is the fiscal year of the REPORT the fact appeared in, so
comparatives inside newer 10-Ks carry the newer filing's fy (verified: AAPL revenue for the year ending
2022-09-24 appears with fy=2022, 2023 AND 2024). min(fy) per period is also unreliable (filer-mislabeled
fy in older filings; tag-history truncation). Rule: fiscal_year = calendar year of period_end — verified
to match all five companies' own FY labels incl. NVDA's late-January year end. Guardrails at ingest: for
anchor facts (end == the filing's reportDate) cross-check the label against the filing's fy; fiscal years
must be strictly increasing by period_end; a per-ticker label offset exists in config for a future company
whose convention differs. Violations log loudly; never load silently.
Dedupe on (concept, period_end): keep max(filed) — the restatement policy (latest-filed-wins) — and CAPTURE
the replaced value into superseded_value/superseded_filed so restatements stay visible to the UI and agent.
Splits: latest-filed-wins is split-consistent ONLY inside the newest filings' 3-year comparative window
(NVDA FY2024 EPS 11.93 pre-split -> 1.19 restated, but FY2022 survives pre-split at 3.85, true ~0.39).
Detect shares_diluted YoY ratio >= 1.5 -> inferred split factor; back-adjust older per-share facts
(EPS / f, shares * f, source_tag += "|split-adjusted"). Persist accession (accn), filed, form, source_tag as
provenance on every row.

## Fiscal-year alignment (a designed trap in this case study — surface it, never hide it)
Expected year-ends: NVDA ~last Sunday of Jan · MSFT Jun 30 · AAPL last Sat of Sep · GOOGL Dec 31 ·
ETN Dec 31. Verify from data, never hardcode dates. Consequence: "last year" across companies means each
company's latest COMPLETED fiscal year — different calendar spans. All comparisons and answers must carry
the label "FY2025 (ended 2025-06-30)" so the user sees the basis.

## 10-K narrative extraction (Item 1A, Item 7)
Normalise the doc: BeautifulSoup(lxml), drop script/style, get_text("\n"), collapse runs of whitespace.
Boundaries (case-insensitive, tolerate "Item 1A.", "ITEM 1A —", nbsp): Item 1A spans from /item\s*1a\b/ to
/item\s*1b\b/; Item 7 from /item\s*7\b(?!a)/ to /item\s*7a\b/. The FIRST matches are usually the table of
contents — collect all candidate spans and take the LAST (equivalently the longest). If the extracted span
< 2000 chars, treat extraction as failed: fall back to item="FULL" whole-document chunks + WARNING. The
brief explicitly allows full-text retrieval as a fallback. Chunking: ~1400 chars, 200 overlap, prefer
paragraph boundaries; store (accession, cik, item, fiscal_year, chunk_index).

## Form 4 (insider transactions, thin slice by design)
From submissions recent filings, form == "4", filed within 12 months, cap 40/company. primaryDocument is
an XSL-rendered wrapper path (e.g. xslF345X06/wk-form4_123.xml) — strip the xslF345X0N/ directory prefix
to fetch the raw XML (<ownershipDocument> root); parse nonDerivativeTable/nonDerivativeTransaction:
transactionCode P (open-market buy)
or S (sale) only; shares, pricePerShare (may be absent -> value NULL), reportingOwner name + officerTitle.
Malformed XML: warn and skip. Downstream summary: 90d/365d buy vs sell counts + net notional.

## Full-text search over chunks
Postgres: tsv tsvector GENERATED from text, GIN index; query with websearch_to_tsquery('english', q),
order by ts_rank, snippet via ts_headline. Filters: cik, item, fiscal_year. SQLite test fallback: same
interface, ILIKE.

## Prices
yfinance period="2y" interval="1d" auto_adjust=True, per ticker, raw CSV cached to bronze. Fallback on any
failure: https://stooq.com/q/d/l/?s={ticker_lower}.us&i=d (same OHLCV shape, log the fallback). Record
source (yfinance | stooq) on every row.
