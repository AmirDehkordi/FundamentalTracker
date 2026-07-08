"""XBRL company-facts parsing: EDGAR payload -> annual FundamentalFact rows (sec-edgar skill §XBRL).

The messy-data core. For each canonical concept we walk its us-gaap tag fallback chain PER FISCAL
YEAR (not per company — see the GOOGL trap in the skill), keep only annual 10-K facts, resolve
restatements latest-filed-wins while preserving the superseded value, and derive gross_profit /
operating_income when a filer stops tagging them directly (e.g. ETN's OperatingIncomeLoss after
FY2019). fiscal_year is the calendar year of period_end — the finance/Bloomberg convention and the
project rule; the entry's own `fy` is deliberately ignored because it is the *report's* year and
mislabels comparative facts inside newer 10-Ks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from tracker.concepts import ALL_STORED_CONCEPTS
from tracker.ingestion import edgar_client

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# us-gaap tag fallback chains, transcribed from the sec-edgar skill. Per fiscal year, the first tag
# in a chain that has that year wins. gross_profit / operating_income also carry a derivation path.
CONCEPT_CHAINS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],  # derivation input only
    "rnd": ["ResearchAndDevelopmentExpense"],  # derivation input only
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

CONCEPT_UNITS: dict[str, str] = {
    "eps_diluted": "USD/shares",
    "shares_diluted": "shares",
    # everything else is USD
    **{c: "USD" for c in CONCEPT_CHAINS if c not in {"eps_diluted", "shares_diluted"}},
}

# Fail loudly at import if the chains drift from the frozen concept vocabulary. Explicit raise (not
# assert) so the guard survives `python -O`.
if set(CONCEPT_CHAINS) != ALL_STORED_CONCEPTS:
    raise RuntimeError("CONCEPT_CHAINS out of sync with concepts.py")

# Annual duration bounds: 10-Ks carry quarterly facts mislabeled fp=FY; real annuals are ~363-370d.
_MIN_DURATION_DAYS = 330
_MAX_DURATION_DAYS = 400
_SPLIT_RATIO = Decimal("1.5")


class FundamentalFact(BaseModel):
    """One annual fact with provenance, ready to upsert into the `fundamentals` table."""

    cik: int
    concept: str
    source_tag: str  # "us-gaap:<Tag>" or "derived:<formula>"
    fiscal_year: int  # = period_end.year
    period_start: date | None
    period_end: date
    value: Decimal
    unit: str
    accession: str
    filed: date
    form: str
    superseded_value: Decimal | None = None
    superseded_filed: date | None = None


@dataclass(frozen=True)
class _Entry:
    """A single us-gaap fact entry passing the annual filters, before dedupe/labelling."""

    end: date
    start: date
    val: Decimal
    accn: str
    filed: date
    form: str
    tag: str


def load_ticker_map(tickers: list[str]) -> dict[str, tuple[int, str]]:
    """Resolve the configured universe to {TICKER: (cik, title)} via SEC's company_tickers.json."""
    payload = edgar_client.get_json(TICKERS_URL)
    wanted = set(tickers)
    found: dict[str, tuple[int, str]] = {}
    for row in payload.values():
        try:
            ticker = str(row["ticker"]).upper()
            if ticker in wanted:
                found[ticker] = (int(row["cik_str"]), str(row["title"]))
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("skipping malformed company_tickers row: %s", exc)
    for ticker in tickers:
        if ticker not in found:
            logger.warning("ticker %s not found in SEC company_tickers.json", ticker)
    return found


def fetch_companyfacts(cik: int) -> Any:
    """Fetch the full XBRL company-facts document for one CIK (bronze-cached by the client)."""
    return edgar_client.get_json(COMPANYFACTS_URL.format(cik=cik))


def _annual_entries(facts: Any, tag: str, unit: str) -> list[_Entry]:
    """Annual 10-K duration facts for one us-gaap tag+unit; malformed entries logged and skipped."""
    node = facts.get(tag)
    if not node:
        return []
    result: list[_Entry] = []
    for entry in node.get("units", {}).get(unit, []):
        try:
            if entry.get("form") != "10-K" or entry.get("fp") != "FY":
                continue
            start_raw = entry.get("start")
            if (
                start_raw is None
            ):  # every canonical concept is a duration; instants can't be annuals
                continue
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(entry["end"])
            if not (_MIN_DURATION_DAYS <= (end - start).days <= _MAX_DURATION_DAYS):
                continue  # rejects quarterly facts that carry fp=FY
            result.append(
                _Entry(
                    end=end,
                    start=start,
                    val=Decimal(str(entry["val"])),
                    accn=str(entry["accn"]),
                    filed=date.fromisoformat(entry["filed"]),
                    form=str(entry["form"]),
                    tag=tag,
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            logger.warning("skipping malformed %s entry: %s", tag, exc)
    return result


def _resolve_chain(facts: Any, chain: list[str], unit: str) -> dict[date, list[_Entry]]:
    """Group entries by period_end; per fiscal year, pick the FIRST chain tag that has that year."""
    claimed: dict[int, str] = {}  # fiscal_year -> winning tag
    by_period: dict[date, list[_Entry]] = {}
    for tag in chain:
        for entry in _annual_entries(facts, tag, unit):
            fiscal_year = entry.end.year
            if claimed.setdefault(fiscal_year, tag) != tag:
                continue  # an earlier tag in the chain already owns this fiscal year
            by_period.setdefault(entry.end, []).append(entry)
    return by_period


def _dedupe(entries: list[_Entry]) -> tuple[_Entry, Decimal | None, date | None]:
    """Latest-filed-wins; capture the immediately-prior filing's value if it was restated."""
    ordered = sorted(entries, key=lambda e: e.filed)
    winner = ordered[-1]
    prior = ordered[-2] if len(ordered) >= 2 else None
    if prior is not None and prior.val != winner.val:
        return winner, prior.val, prior.filed
    return winner, None, None


def _latest_input(*facts: FundamentalFact) -> FundamentalFact:
    """Provenance for a derived row = the latest-filed of its inputs (skill)."""
    return max(facts, key=lambda f: f.filed)


def _fact_from_entry(cik: int, concept: str, unit: str, entries: list[_Entry]) -> FundamentalFact:
    winner, superseded_value, superseded_filed = _dedupe(entries)
    return FundamentalFact(
        cik=cik,
        concept=concept,
        source_tag=f"us-gaap:{winner.tag}",
        fiscal_year=winner.end.year,
        period_start=winner.start,
        period_end=winner.end,
        value=winner.val,
        unit=unit,
        accession=winner.accn,
        filed=winner.filed,
        form=winner.form,
        superseded_value=superseded_value,
        superseded_filed=superseded_filed,
    )


def _derive(
    cik: int,
    concept: str,
    source_tag: str,
    value: Decimal,
    base: FundamentalFact,
    inputs: list[FundamentalFact],
) -> FundamentalFact:
    latest = _latest_input(*inputs)
    return FundamentalFact(
        cik=cik,
        concept=concept,
        source_tag=source_tag,
        fiscal_year=base.period_end.year,
        period_start=base.period_start,
        period_end=base.period_end,
        value=value,
        unit="USD",
        accession=latest.accession,
        filed=latest.filed,
        form=latest.form,
    )


def _fill_derivations(cik: int, resolved: dict[str, dict[date, FundamentalFact]]) -> None:
    """Add gross_profit / operating_income for years lacking a direct tag (in place)."""
    revenue, cost = resolved["revenue"], resolved["cost_of_revenue"]
    gross_profit, operating_income = resolved["gross_profit"], resolved["operating_income"]
    sga, rnd = resolved["sga"], resolved["rnd"]

    for end, rev in revenue.items():
        cor = cost.get(end)
        if end not in gross_profit and cor is not None:
            gross_profit[end] = _derive(
                cik,
                "gross_profit",
                "derived:revenue-cost_of_revenue",
                rev.value - cor.value,
                rev,
                [rev, cor],
            )
        if end not in operating_income:
            comps = {"cost_of_revenue": cor, "sga": sga.get(end), "rnd": rnd.get(end)}
            missing = [name for name, f in comps.items() if f is None]
            if missing:
                logger.info("operating_income FY%d not derivable: missing %s", end.year, missing)
                continue
            c, s, d = comps["cost_of_revenue"], comps["sga"], comps["rnd"]
            assert c is not None and s is not None and d is not None  # narrowed by `missing` check
            operating_income[end] = _derive(
                cik,
                "operating_income",
                "derived:revenue-cost_of_revenue-sga-rnd",
                rev.value - c.value - s.value - d.value,
                rev,
                [rev, c, s, d],
            )


def _run_guardrails(resolved: dict[str, dict[date, FundamentalFact]]) -> None:
    """Surface fiscal-alignment anomalies loudly; never mutate or drop silently (skill)."""
    for concept, per_period in resolved.items():
        years = [f.fiscal_year for f in per_period.values()]
        if len(set(years)) != len(years):
            logger.warning("%s: two period_ends map to one fiscal_year: %s", concept, sorted(years))

    shares = sorted(resolved["shares_diluted"].values(), key=lambda f: f.period_end)
    for prev, cur in zip(shares, shares[1:], strict=False):
        if prev.value and cur.value / prev.value >= _SPLIT_RATIO:
            logger.warning(
                "shares_diluted jumped ~%.1fx (FY%d->FY%d): likely split; per-share "
                "back-adjustment deferred to a later phase",
                cur.value / prev.value,
                prev.fiscal_year,
                cur.fiscal_year,
            )


def extract_annual_facts(payload: dict[str, Any]) -> list[FundamentalFact]:
    """Parse one company-facts payload into annual FundamentalFact rows (see module docstring)."""
    cik = int(payload["cik"])
    facts = payload.get("facts", {}).get("us-gaap", {})

    resolved: dict[str, dict[date, FundamentalFact]] = {}
    for concept, chain in CONCEPT_CHAINS.items():
        unit = CONCEPT_UNITS[concept]
        resolved[concept] = {
            end: _fact_from_entry(cik, concept, unit, entries)
            for end, entries in _resolve_chain(facts, chain, unit).items()
        }

    _fill_derivations(cik, resolved)
    _run_guardrails(resolved)

    return [fact for per_period in resolved.values() for fact in per_period.values()]
