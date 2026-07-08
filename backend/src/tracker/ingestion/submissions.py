"""SEC submissions endpoint: CIK -> recent-filings index (sec-edgar skill).

`filings.recent` is COLUMN-oriented — parallel arrays form[], accessionNumber[], primaryDocument[],
filingDate[], reportDate[]. Zip them once here so filings.py and form4.py share one correct,
length-guarded reader instead of re-deriving the ragged-array hazard twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from tracker.ingestion import edgar_client

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


@dataclass(frozen=True)
class RecentFiling:
    """One row of the submissions recent-filings index."""

    form: str
    accession: str
    primary_document: str
    filing_date: date
    report_date: date | None  # empty for non-periodic forms; period_end for a 10-K


def fetch(cik: int) -> Any:
    """Fetch the submissions document for one CIK (bronze-cached by the client)."""
    return edgar_client.get_json(SUBMISSIONS_URL.format(cik=cik))


def _parse_report_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None  # lenient: a bad reportDate must not drop the row (10-Ks are re-checked later)


def recent_filings(payload: Any) -> list[RecentFiling]:
    """Zip the parallel recent-filings arrays into typed rows; malformed rows logged and skipped."""
    recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    filed = recent.get("filingDate", [])
    reported = recent.get("reportDate", [])

    lengths = {len(forms), len(accessions), len(docs), len(filed), len(reported)}
    n = min(lengths) if lengths else 0
    if len(lengths) > 1:
        logger.warning("submissions recent arrays are ragged; truncating to %d rows", n)

    rows: list[RecentFiling] = []
    for i in range(n):
        try:
            filing_date = date.fromisoformat(str(filed[i]))
        except (ValueError, TypeError) as exc:  # filingDate is required — skip an unusable row
            logger.warning("skipping submissions row %d: bad filingDate: %s", i, exc)
            continue
        rows.append(
            RecentFiling(
                form=str(forms[i]),
                accession=str(accessions[i]),
                primary_document=str(docs[i]),
                filing_date=filing_date,
                report_date=_parse_report_date(str(reported[i])),
            )
        )
    return rows
