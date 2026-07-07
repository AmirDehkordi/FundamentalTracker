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

## Canonical concepts and us-gaap tag fallback chains (try in order, first hit wins)
revenue:          RevenueFromContractWithCustomerExcludingAssessedTax -> Revenues -> SalesRevenueNet
net_income:       NetIncomeLoss
eps_diluted:      EarningsPerShareDiluted            (units: USD/shares)
gross_profit:     GrossProfit -> derive revenue - cost_of_revenue (tag derived:...)
cost_of_revenue:  CostOfRevenue -> CostOfGoodsAndServicesSold
operating_income: OperatingIncomeLoss
cfo:              NetCashProvidedByUsedInOperatingActivities
capex:            PaymentsToAcquirePropertyPlantAndEquipment
shares_diluted:   WeightedAverageNumberOfDilutedSharesOutstanding   (units: shares)
Alphabet reports cost of revenues but not GrossProfit — derivation is expected, not exceptional.

## Selecting annual facts (the messy-data core)
Keep entries where form == "10-K" AND fp == "FY". For duration concepts require 330 <= (end-start).days
<= 400 (rejects quarters). fiscal_year = the entry's "fy". Dedupe on (concept, end): keep max(filed) —
this is the restatement policy (latest-filed-wins) and it also picks up split-adjusted comparatives (e.g.
NVDA's post-split EPS restated in the newer filing). Persist accession (accn), filed, form, source_tag as
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
From submissions recent filings, form == "4", filed within 12 months, cap 40/company. Fetch the filing's
XML primary document; parse nonDerivativeTable/nonDerivativeTransaction: transactionCode P (open-market buy)
or S (sale) only; shares, pricePerShare (may be absent -> value NULL), reportingOwner name + officerTitle.
Malformed XML: warn and skip. Downstream summary: 90d/365d buy vs sell counts + net notional.

## Full-text search over chunks
Postgres: tsv tsvector GENERATED from text, GIN index; query with websearch_to_tsquery('english', q),
order by ts_rank, snippet via ts_headline. Filters: cik, item, fiscal_year. SQLite test fallback: same
interface, ILIKE.

## Prices
yfinance period="2y" interval="1d" auto_adjust=True, per ticker, raw CSV cached to bronze. Fallback on any
failure: https://stooq.com/q/d/l/?s={ticker_lower}.us&i=d (same OHLCV shape, log the fallback).
