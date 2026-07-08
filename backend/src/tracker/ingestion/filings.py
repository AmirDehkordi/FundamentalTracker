"""10-K narrative extraction: submissions index -> Item 1A / Item 7 text chunks (sec-edgar skill).

Normalise the primary document with BeautifulSoup(lxml), extract the Item 1A (risk factors) and
Item 7 (MD&A) sections, and chunk them for retrieval. The extraction is the trap: the first
"Item 1A ... Item 1B" run in a 10-K is the table of contents, and an in-prose "see Item 7A"
cross-reference will truncate MD&A if treated as the 7A heading. We defend with LINE-ANCHORED
heading regexes (a real heading owns its line; a cross-reference is mid-sentence) and pick the
LONGEST anchored span (the real body dwarfs TOC entries and running-header repeats). If a section
still comes up < 2000 chars extraction is deemed failed and we fall back to whole-document chunks.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup
from pydantic import BaseModel

from tracker.ingestion import edgar_client
from tracker.ingestion.submissions import RecentFiling

logger = logging.getLogger(__name__)

ARCHIVES_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{doc}"

_MIN_ITEM_CHARS = 2000  # below this a section is treated as an extraction failure -> FULL fallback
_CHUNK_SIZE = 1400
_CHUNK_OVERLAP = 200

# Line-anchored (^\W* + MULTILINE) heading markers. ^\W* tolerates leading bullets/blank lines/nbsp
# but rejects a mid-sentence "see Item 7A", the classic MD&A-truncation bug. \s matches nbsp (\xa0).
_FLAGS = re.IGNORECASE | re.MULTILINE
_ITEM_1A = re.compile(r"^\W*item\s*1a\b", _FLAGS)
_ITEM_1B = re.compile(r"^\W*item\s*1b\b", _FLAGS)
_ITEM_2 = re.compile(r"^\W*item\s*2\b", _FLAGS)  # fallback boundary when Item 1B is absent
_ITEM_7 = re.compile(r"^\W*item\s*7\b(?!a)", _FLAGS)
_ITEM_7A = re.compile(r"^\W*item\s*7a\b", _FLAGS)
_ITEM_8 = re.compile(r"^\W*item\s*8\b", _FLAGS)  # fallback boundary when Item 7A is absent

# Some filers (e.g. ETN/Eaton) make the "Item 7" heading a bare cross-reference and put the MD&A
# under a standalone title. When the Item 7 span is a stub, extract that titled section instead.
_MDNA_TITLE = re.compile(r"^\W*management.?s\s+discussion\s+and\s+analysis", _FLAGS)
_MARKET_RISK = re.compile(r"^\W*market\s+risk\s+disclosure\b", _FLAGS)

# (start, primary boundary, fallback boundary) per supported item.
_ITEM_BOUNDS: dict[str, tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]] = {
    "1A": (_ITEM_1A, _ITEM_1B, _ITEM_2),
    "7": (_ITEM_7, _ITEM_7A, _ITEM_8),
}


class FilingRow(BaseModel):
    """One 10-K filing header, ready to upsert into the `filings` table."""

    accession: str
    cik: int
    form: str
    fiscal_year: int  # = period_end.year
    period_end: date
    filed: date
    primary_doc_url: str


class ChunkRow(BaseModel):
    """One narrative chunk for `filing_chunks` (the tsv column is generated, never written here)."""

    accession: str
    cik: int
    item: str  # 1A | 7 | FULL
    fiscal_year: int
    chunk_index: int
    text: str


def select_recent_10ks(records: list[RecentFiling], limit: int = 2) -> list[RecentFiling]:
    """The `limit` most recently filed 10-Ks (exact form, excludes 10-K/A amendments)."""
    tenks: list[RecentFiling] = []
    for r in records:
        if r.form != "10-K":  # exact — 10-K/A restatements are reconciled in the XBRL lane
            continue
        if r.report_date is None or not r.primary_document:
            logger.warning("skipping 10-K %s: missing reportDate or primaryDocument", r.accession)
            continue
        tenks.append(r)
    tenks.sort(key=lambda r: r.filing_date, reverse=True)
    return tenks[:limit]


def fetch_primary_doc(url: str) -> str:
    """Download a filing's primary document (bronze-cached) and decode as text."""
    return edgar_client.get_bytes(url).decode("utf-8", "replace")


def html_to_text(html: str) -> str:
    """Strip a 10-K to text: drop script/style, get_text("\\n"), collapse whitespace per line.

    Keeps one `\\n` between non-empty source lines so the chunker has paragraph boundaries and the
    line-anchored item regexes have real line starts to match.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = []
    for line in soup.get_text("\n").split("\n"):
        collapsed = re.sub(r"\s+", " ", line).strip()  # \s matches nbsp (\xa0), tabs, stray runs
        if collapsed:
            lines.append(collapsed)
    return "\n".join(lines)


def _extract_span(
    text: str,
    start_re: re.Pattern[str],
    primary_re: re.Pattern[str],
    fallback_re: re.Pattern[str],
) -> str:
    """Longest line-anchored span from a start heading to its first following boundary heading."""
    starts = [m.start() for m in start_re.finditer(text)]
    if not starts:
        return ""
    primaries = [m.start() for m in primary_re.finditer(text)]
    fallbacks = [m.start() for m in fallback_re.finditer(text)]
    best = ""
    for start in starts:
        after_primary = [p for p in primaries if p > start]
        after_fallback = [p for p in fallbacks if p > start]
        if after_primary:
            end = min(after_primary)
        elif after_fallback:
            end = min(after_fallback)
        else:
            end = len(text)
        span = text[start:end].strip()
        if len(span) > len(best):
            best = span
    return best


def _nearest_span(
    text: str, start_re: re.Pattern[str], boundary_res: tuple[re.Pattern[str], ...]
) -> str:
    """Longest span from a line-anchored start to the NEAREST following boundary of any kind.

    Unlike _extract_span (which prefers its primary boundary), this bounds each start at the closest
    boundary — so a table-of-contents start is clipped by its adjacent TOC entry, not a far one.
    """
    starts = [m.start() for m in start_re.finditer(text)]
    ends = sorted(m.start() for br in boundary_res for m in br.finditer(text))
    best = ""
    for start in starts:
        after = [e for e in ends if e > start]
        end = after[0] if after else len(text)
        span = text[start:end].strip()
        if len(span) > len(best):
            best = span
    return best


def extract_item(text: str, item: str) -> str:
    """Extract one 10-K item's narrative text (see module docstring for the heuristic)."""
    try:
        start_re, primary_re, fallback_re = _ITEM_BOUNDS[item]
    except KeyError:
        raise ValueError(f"unsupported item {item!r}") from None
    span = _extract_span(text, start_re, primary_re, fallback_re)
    if item == "7" and len(span) < _MIN_ITEM_CHARS:
        # Item 7 is a cross-reference stub — recover the MD&A from its standalone title section.
        titled = _nearest_span(text, _MDNA_TITLE, (_MARKET_RISK, _ITEM_7A, _ITEM_8))
        if len(titled) > len(span):
            return titled
    return span


def _extract_items(text: str, ticker: str, accession: str) -> dict[str, str]:
    """{item: text} for 1A and 7 that clear the length floor; else {'FULL': whole doc} + WARNING."""
    items: dict[str, str] = {}
    for item in ("1A", "7"):
        span = extract_item(text, item)
        if len(span) >= _MIN_ITEM_CHARS:
            items[item] = span
    if not items:
        logger.warning(
            "10-K item extraction < %d chars for both 1A and 7 (ticker=%s accession=%s); "
            "falling back to FULL-document chunking",
            _MIN_ITEM_CHARS,
            ticker,
            accession,
        )
        items["FULL"] = text
    return items


def chunk(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split `text` into ~`size`-char windows overlapping by `overlap`, preferring `\\n` breaks.

    Invariants (see tests): strict forward progress (stride >= size - 2*overlap), no dropped chars,
    consecutive chunks share exactly their `overlap` boundary, every chunk <= size.
    """
    if not (overlap < size and size > 2 * overlap):
        raise ValueError("chunk requires overlap < size and size > 2*overlap")
    if not text.strip():
        return []
    n = len(text)
    if n <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while True:
        end = min(start + size, n)
        if end < n:
            # Prefer a paragraph break, but only in the window tail so the stride stays positive.
            brk = text.rfind("\n", start + (size - overlap), end)
            if brk != -1:
                end = brk
        chunks.append(text[start:end])
        if end >= n:
            return chunks
        start = end - overlap


def build_filing_chunks(
    cik: int, ticker: str, records: list[RecentFiling]
) -> tuple[list[FilingRow], list[ChunkRow]]:
    """Fetch + chunk the two most recent 10-Ks for one company into filing + chunk rows."""
    filing_rows: list[FilingRow] = []
    chunk_rows: list[ChunkRow] = []
    for tenk in select_recent_10ks(records):
        if tenk.report_date is None:  # guaranteed by select_recent_10ks; keeps mypy + runtime safe
            continue
        nodash = tenk.accession.replace("-", "")
        url = ARCHIVES_DOC_URL.format(cik=cik, nodash=nodash, doc=tenk.primary_document)
        fiscal_year = tenk.report_date.year
        filing_rows.append(
            FilingRow(
                accession=tenk.accession,
                cik=cik,
                form="10-K",
                fiscal_year=fiscal_year,
                period_end=tenk.report_date,
                filed=tenk.filing_date,
                primary_doc_url=url,
            )
        )
        try:
            html = fetch_primary_doc(url)
        except Exception:  # a bad doc keeps the filing header but yields no chunks — never crashes
            logger.exception(
                "failed to fetch 10-K doc for %s (%s); filing kept, chunks skipped",
                ticker,
                tenk.accession,
            )
            continue
        text = html_to_text(html)
        for item, body in _extract_items(text, ticker, tenk.accession).items():
            for idx, piece in enumerate(chunk(body)):
                chunk_rows.append(
                    ChunkRow(
                        accession=tenk.accession,
                        cik=cik,
                        item=item,
                        fiscal_year=fiscal_year,
                        chunk_index=idx,
                        text=piece,
                    )
                )
    return filing_rows, chunk_rows
