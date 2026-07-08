"""Form 4 insider transactions: submissions index -> open-market buy/sell rows (sec-edgar skill).

A deliberately thin slice: from a company's recent filings take form=="4" within the last 12 months
(cap 40), fetch each raw ownership XML, and keep only nonDerivativeTransaction rows with
transactionCode P (open-market buy) or S (sale). The primaryDocument is an XSL-rendered wrapper path
(xslF345X0N/...) — strip that prefix to reach the raw <ownershipDocument> XML. Parsing is
namespace-agnostic (local-name()) so a future namespaced document does not silently yield zero rows,
and uses a hardened parser (no external entities / DTD / network) on this semi-trusted XML.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import etree
from pydantic import BaseModel

from tracker.ingestion import edgar_client
from tracker.ingestion.filings import ARCHIVES_DOC_URL
from tracker.ingestion.submissions import RecentFiling

logger = logging.getLogger(__name__)

_XSL_PREFIX = re.compile(r"^xslF345X\d+/")
_WINDOW_DAYS = 365
_CAP_PER_COMPANY = 40

# Column scales — quantize here so a value is identical on SQLite (unit) and Postgres (prod); SQLite
# stores NUMERIC as float and would otherwise round differently from Postgres NUMERIC(p, s).
_SHARES_Q = Decimal("0.0001")
_PRICE_Q = Decimal("0.000001")
_MONEY_Q = Decimal("0.000001")

# XXE / billion-laughs defense on semi-trusted SEC XML: no entity expansion, no DTD, no network.
_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, recover=False
)


class InsiderTxn(BaseModel):
    """One Form 4 open-market transaction, ready to upsert into `insider_transactions`."""

    cik: int
    accession: str
    filed: date
    insider_name: str
    role: str | None
    code: str  # P | S
    shares: Decimal
    price: Decimal | None  # absent when the filing prices via footnote only
    value: Decimal | None  # shares * price when price is present


def raw_xml_name(primary_document: str) -> str:
    """Strip the xslF345X0N/ XSL-wrapper prefix to reach the raw ownership XML (no-op if absent)."""
    return _XSL_PREFIX.sub("", primary_document)


def select_form4_filings(
    records: list[RecentFiling], as_of: date, cap: int = _CAP_PER_COMPANY
) -> list[RecentFiling]:
    """The most recent form=="4" filings within 12 months of `as_of`, capped, newest first."""
    cutoff = as_of - timedelta(days=_WINDOW_DAYS)
    selected = [
        r
        for r in records
        if r.form == "4" and r.filing_date >= cutoff and r.primary_document  # exact 4 (not 4/A)
    ]
    selected.sort(key=lambda r: r.filing_date, reverse=True)
    return selected[:cap]


def fetch_form4_xml(cik: int, accession: str, primary_document: str) -> bytes:
    """Download a Form 4's raw ownership XML (bronze-cached)."""
    nodash = accession.replace("-", "")
    url = ARCHIVES_DOC_URL.format(cik=cik, nodash=nodash, doc=raw_xml_name(primary_document))
    return edgar_client.get_bytes(url)


def _decimal_at(node: Any, tag: str, quant: Decimal) -> Decimal | None:
    """Quantized Decimal from <tag><value>…</value></tag> under `node`, or None if absent/blank."""
    vals = node.xpath(f".//*[local-name()='{tag}']/*[local-name()='value']/text()")
    if not vals or not str(vals[0]).strip():
        return None
    try:
        return Decimal(str(vals[0]).strip()).quantize(quant)
    except InvalidOperation:
        return None


def parse_form4_xml(xml: bytes, cik: int, accession: str, filed: date) -> list[InsiderTxn]:
    """Parse one Form 4 ownership XML into P/S transactions; malformed XML is warned and skipped.

    A joint (multi-owner) filing attributes all transactions to the first reportingOwner — the
    standard document-level reading for this thin slice.
    """
    try:
        root = etree.fromstring(xml, _PARSER)
    except etree.XMLSyntaxError as exc:  # truncated / entity-laden / otherwise unparseable
        logger.warning("skipping malformed Form 4 %s: %s", accession, exc)
        return []

    owners = root.xpath("//*[local-name()='reportingOwner']")
    if not owners:
        logger.warning("Form 4 %s has no reportingOwner; skipping", accession)
        return []
    owner = owners[0]
    names = owner.xpath(".//*[local-name()='rptOwnerName']/text()")
    insider_name = str(names[0]).strip() if names else ""
    if not insider_name:
        logger.warning("Form 4 %s missing reporting-owner name; skipping", accession)
        return []
    titles = owner.xpath(".//*[local-name()='officerTitle']/text()")
    role = str(titles[0]).strip() if titles and str(titles[0]).strip() else None

    txns: list[InsiderTxn] = []
    for node in root.xpath("//*[local-name()='nonDerivativeTransaction']"):
        codes = node.xpath(".//*[local-name()='transactionCode']/text()")
        code = str(codes[0]).strip() if codes else ""
        if code not in ("P", "S"):  # open-market buy/sell only (thin slice by design)
            continue
        shares = _decimal_at(node, "transactionShares", _SHARES_Q)
        if shares is None:
            logger.warning("Form 4 %s transaction missing shares; skipping row", accession)
            continue
        price = _decimal_at(node, "transactionPricePerShare", _PRICE_Q)
        value = (shares * price).quantize(_MONEY_Q) if price is not None else None
        txns.append(
            InsiderTxn(
                cik=cik,
                accession=accession,
                filed=filed,
                insider_name=insider_name,
                role=role,
                code=code,
                shares=shares,
                price=price,
                value=value,
            )
        )
    return txns


def _dedupe_batch(txns: list[InsiderTxn]) -> list[InsiderTxn]:
    """Collapse rows sharing the (accession, insider_name, code, shares, filed) natural key.

    The single ON CONFLICT insert must not target the same row twice ("cannot affect row a second
    time" on Postgres). Multi-tranche same-day sales (10b5-1 plans often split an identical share
    count across prices) DO collide — the frozen key cannot hold both — so a *lossy* collapse (a
    dropped tranche with a differing price/value) is logged loudly, not silently undercounted.
    """
    deduped: dict[tuple[str, str, str, Decimal, date], InsiderTxn] = {}
    for t in txns:
        key = (t.accession, t.insider_name, t.code, t.shares, t.filed)
        prior = deduped.get(key)
        # value = shares*price and shares is in the key, so a differing price is the sole signal of
        # a distinct (lossy) tranche; equal-price rows are true duplicates, collapsed quietly.
        if prior is not None and prior.price != t.price:
            logger.warning(
                "Form 4 %s: collapsing a same-day %s lot of %s shares for %s "
                "(price %s superseded by %s); the natural key cannot hold both tranches",
                t.accession,
                t.code,
                t.shares,
                t.insider_name,
                prior.price,
                t.price,
            )
        deduped[key] = t  # last wins
    return list(deduped.values())


def build_insider_txns(cik: int, records: list[RecentFiling], as_of: date) -> list[InsiderTxn]:
    """Fetch + parse a company's recent Form 4s into deduped insider rows; a bad XML is skipped."""
    txns: list[InsiderTxn] = []
    for r in select_form4_filings(records, as_of):
        try:
            xml = fetch_form4_xml(cik, r.accession, r.primary_document)
            txns.extend(parse_form4_xml(xml, cik, r.accession, r.filing_date))
        except Exception:  # a fetch/parse failure on one filing must not crash the company run
            logger.exception("failed to fetch/parse Form 4 %s; skipping", r.accession)
    return _dedupe_batch(txns)
