"""Risk-factor diff: a DETERMINISTIC Item 1A year-over-year diff — NO LLM here (PLAN.md §8, §14).

Paragraphs are paired by best difflib.SequenceMatcher ratio (≥ 0.75 = unchanged), never positionally
— year-over-year 10-Ks reorder and reflow, so a positional diff degenerates into "everything
changed". This module only produces the added/removed paragraph excerpts + counts; the agent
summarises that output downstream. Thresholds are tuned on synthetic paragraphs now and are to be
re-tuned against the real NVDA FY2024↔FY2025 1A pair before the UI card is built.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.db.models import Company, Filing, FilingChunk
from tracker.services.fiscal import format_fy_label

OVERLAP_PROBE = 400  # chars of head/tail scanned for the ~200-char inter-chunk overlap
MIN_OVERLAP = 30  # ignore incidental short common runs when de-overlapping
# Tuned DOWN from 0.75: a reworded risk factor (same substance, reflowed sentences) should pair as
# "unchanged", not surface as both added AND removed. Combined with the noise filters below, this
# brings the counts to what a human would call "what actually changed" (MSFT's 36/42 collapses).
SIMILARITY_THRESHOLD = 0.66  # SequenceMatcher ratio at/above which two paragraphs are "unchanged"
MERGE_THRESHOLD = 0.97  # intra-year: only NEAR-IDENTICAL paragraphs (repeated boilerplate) collapse
MIN_PARAGRAPH_CHARS = 120  # drop sub-sentence fragments (headers, captions, page furniture)
EXCERPT_CHARS = 240  # per-paragraph excerpt cap
# Real EDGAR Item 1A text delimits each risk factor with a SINGLE newline (bullets sit on their own
# "•" lines), not blank lines. Splitting only on blank lines collapsed the whole ~115KB section into
# one paragraph, and _pair's O(n²) ratio() on two such blobs took ~100s. Split on any newline run,
# dropping marker-only lines, so pairing runs on real, per-risk-factor paragraphs.
_PARAGRAPH_SPLIT = re.compile(r"\n+")
# Page furniture / section chrome that reflows year over year and inflates the diff. Matched against
# the whitespace-collapsed paragraph; most such lines are also caught by the <120-char floor.
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}(\s*[|/].*)?$", re.IGNORECASE)
_BOILERPLATE = re.compile(
    r"^(table of contents|item\s*1a\.?(\s*risk factors)?|risk factors|"
    r"part\s+[ivx]+|form\s*10-?k.*)$",
    re.IGNORECASE,
)

RISKDIFF_UNAVAILABLE_NOTE = (
    "Item 1A year-over-year diff unavailable: fewer than two fiscal years of extracted "
    "risk-factor text."
)


@dataclass(frozen=True, slots=True)
class FilingRefData:
    """Mirrors schemas.FilingRef."""

    fiscal_year: int
    period_end: date
    accession: str
    primary_doc_url: str
    label: str


@dataclass(frozen=True, slots=True)
class RiskDiffCountsData:
    """Mirrors schemas.RiskDiffCounts."""

    added: int
    removed: int
    unchanged: int | None = None


@dataclass(frozen=True, slots=True)
class RiskDiffResult:
    """Mirrors schemas.RiskDiffOut. `latest`/`prior` are None only in the degraded state."""

    ticker: str
    cik: int
    item: str
    latest: FilingRefData | None
    prior: FilingRefData | None
    added: list[str]
    removed: list[str]
    counts: RiskDiffCountsData
    available: bool = True
    note: str | None = None


def diff_risk_factors(session: Session, cik: int, item: str = "1A") -> RiskDiffResult:
    """Diff the two most-recent stored fiscal years of `item` for a company."""
    ticker = _ticker(session, cik)
    fiscal_years = list(
        session.scalars(
            select(FilingChunk.fiscal_year)
            .where(FilingChunk.cik == cik, FilingChunk.item == item)
            .distinct()
            .order_by(FilingChunk.fiscal_year.desc())
            .limit(2)
        ).all()
    )
    if len(fiscal_years) < 2:
        return _degraded(session, ticker, cik, item, fiscal_years)

    latest_ref = _filing_ref(session, cik, item, fiscal_years[0])
    prior_ref = _filing_ref(session, cik, item, fiscal_years[1])
    if latest_ref is None or prior_ref is None:
        return _degraded(session, ticker, cik, item, fiscal_years)

    latest_paras = _reconstruct(_chunks(session, cik, item, fiscal_years[0]))
    prior_paras = _reconstruct(_chunks(session, cik, item, fiscal_years[1]))
    added, removed, unchanged = _pair(prior_paras, latest_paras)
    return RiskDiffResult(
        ticker=ticker,
        cik=cik,
        item=item,
        latest=latest_ref,
        prior=prior_ref,
        added=added,
        removed=removed,
        counts=RiskDiffCountsData(added=len(added), removed=len(removed), unchanged=unchanged),
        available=True,
        note=None,
    )


def _degraded(
    session: Session, ticker: str, cik: int, item: str, fiscal_years: list[int]
) -> RiskDiffResult:
    latest_ref = _filing_ref(session, cik, item, fiscal_years[0]) if fiscal_years else None
    return RiskDiffResult(
        ticker=ticker,
        cik=cik,
        item=item,
        latest=latest_ref,
        prior=None,
        added=[],
        removed=[],
        counts=RiskDiffCountsData(added=0, removed=0, unchanged=0),
        available=False,
        note=RISKDIFF_UNAVAILABLE_NOTE,
    )


def _ticker(session: Session, cik: int) -> str:
    company = session.get(Company, cik)
    return company.ticker if company is not None else ""


def _chunks(session: Session, cik: int, item: str, fiscal_year: int) -> list[FilingChunk]:
    return list(
        session.scalars(
            select(FilingChunk)
            .where(
                FilingChunk.cik == cik,
                FilingChunk.item == item,
                FilingChunk.fiscal_year == fiscal_year,
            )
            .order_by(FilingChunk.chunk_index)
        ).all()
    )


def _filing_ref(session: Session, cik: int, item: str, fiscal_year: int) -> FilingRefData | None:
    chunk = session.scalars(
        select(FilingChunk)
        .where(
            FilingChunk.cik == cik,
            FilingChunk.item == item,
            FilingChunk.fiscal_year == fiscal_year,
        )
        .order_by(FilingChunk.chunk_index)
        .limit(1)
    ).first()
    if chunk is None:
        return None
    filing = session.get(Filing, chunk.accession)
    if filing is None:  # chunk without its parent filing (SQLite does not enforce the FK) — degrade
        return None
    return FilingRefData(
        fiscal_year=fiscal_year,
        period_end=filing.period_end,
        accession=filing.accession,
        primary_doc_url=filing.primary_doc_url,
        label=format_fy_label(fiscal_year, filing.period_end),
    )


def _reconstruct(chunks: list[FilingChunk]) -> list[str]:
    """Rebuild the section text from ordered chunks, trimming the ~200-char inter-chunk overlap."""
    if not chunks:
        return []
    text = chunks[0].text
    for chunk in chunks[1:]:
        head = chunk.text[:OVERLAP_PROBE]
        tail = text[-OVERLAP_PROBE:]
        match = SequenceMatcher(None, tail, head, autojunk=False).find_longest_match(
            0, len(tail), 0, len(head)
        )
        # Accept only a boundary overlap: the run ends `tail` and starts `head`.
        if match.size >= MIN_OVERLAP and match.a + match.size == len(tail) and match.b == 0:
            text += chunk.text[match.size :]
        else:
            text += "\n\n" + chunk.text
    # `any(isalnum)` drops bare bullet/marker lines (a lone "•"); `_denoise` then drops page
    # furniture / sub-sentence fragments and collapses intra-year near-duplicate boilerplate, so
    # `_pair` sees real, distinct risk-factor paragraphs and the counts reflect substance.
    paras = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if any(ch.isalnum() for ch in p)]
    return _denoise(paras)


def _is_noise(paragraph: str) -> bool:
    """A paragraph that carries no risk-factor substance: page numbers, section headers/captions,
    and sub-sentence fragments that reflow year over year and inflate the diff."""
    collapsed = " ".join(paragraph.split())
    if len(collapsed) < MIN_PARAGRAPH_CHARS:
        return True
    return bool(_PAGE_NUMBER.match(collapsed) or _BOILERPLATE.match(collapsed))


def _denoise(paragraphs: list[str]) -> list[str]:
    """Drop noise paragraphs, then collapse intra-year near-duplicates (repeated boilerplate) so a
    paragraph that appears twice in one filing can't count as one added + one removed next year."""
    kept: list[str] = []
    kept_words: list[list[str]] = []
    for para in paragraphs:
        if _is_noise(para):
            continue
        words = _normalize(para).split()
        if any(_word_ratio(words, kw) >= MERGE_THRESHOLD for kw in kept_words):
            continue  # a near-identical paragraph already kept this year
        kept.append(para)
        kept_words.append(words)
    return kept


def _word_ratio(a: list[str], b: list[str], threshold: float = 0.0) -> float:
    """SequenceMatcher word-level ratio with the cheap length/quick_ratio prunes (0.0 below
    `threshold`). Word granularity + autojunk off is accurate and ~300x faster on long text."""
    la, lb = len(a), len(b)
    if la == 0 or lb == 0 or 2.0 * min(la, lb) / (la + lb) < threshold:
        return 0.0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if threshold and matcher.quick_ratio() < threshold:
        return 0.0
    return matcher.ratio()


def _normalize(paragraph: str) -> str:
    """Lowercase + collapse whitespace — for matching only; excerpts stay human-readable."""
    return " ".join(paragraph.lower().split())


def _excerpt(paragraph: str) -> str:
    return " ".join(paragraph.split())[:EXCERPT_CHARS]


def _pair(prior_paras: list[str], latest_paras: list[str]) -> tuple[list[str], list[str], int]:
    """Greedy best-ratio pairing. Returns (added, removed, unchanged_count).

    Real 10-Ks carry ~250 Item 1A paragraphs and reuse most of them verbatim year over year, so an
    all-pairs SequenceMatcher (256² builds) was pathologically slow. Pair identical paragraphs first
    in O(n) — that is exactly what the ratio=1.0 sort did anyway — then fuzzy-match only the changed
    residual, skipping length-incompatible pairs before building a matcher at all."""
    prior_n = [_normalize(p) for p in prior_paras]
    latest_n = [_normalize(p) for p in latest_paras]
    used_prior: set[int] = set()
    used_latest: set[int] = set()

    # Exact matches: identical normalised paragraphs are trivially unchanged (ratio 1.0 wins the
    # greedy sort anyway). Consuming them here shrinks the O(n²) fuzzy search to the real diff.
    latest_by_text: dict[str, list[int]] = {}
    for j, ln in enumerate(latest_n):
        latest_by_text.setdefault(ln, []).append(j)
    for i, pn in enumerate(prior_n):
        bucket = latest_by_text.get(pn)
        if bucket:
            used_prior.add(i)
            used_latest.add(bucket.pop())

    # Fuzzy-pair the residual at WORD granularity with autojunk off. On long 1A
    # paragraphs char-level autojunk=True craters ratio() (it junks every common
    # letter), misclassifying a reworded risk factor as both removed AND added.
    # Char-level autojunk=False is correct but O(n^2) slow; ~50-word sequences are
    # accurate (autojunk off) and ~300x faster — NVDA drops from ~14s to ~0.05s.
    # (_reconstruct still matches characters — it needs the exact overlap run.)
    prior_w = [pn.split() for pn in prior_n]
    latest_w = [ln.split() for ln in latest_n]
    candidates: list[tuple[float, int, int]] = []
    for i in range(len(prior_w)):
        if i in used_prior:
            continue
        pw = prior_w[i]
        for j in range(len(latest_w)):
            if j in used_latest:
                continue
            ratio = _word_ratio(pw, latest_w[j], SIMILARITY_THRESHOLD)  # 0.0 below threshold
            if ratio >= SIMILARITY_THRESHOLD:
                candidates.append((ratio, i, j))

    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))  # best first; (i, j) tie-break = determinism
    for _ratio, i, j in candidates:
        if i in used_prior or j in used_latest:
            continue
        used_prior.add(i)
        used_latest.add(j)

    removed = [_excerpt(prior_paras[i]) for i in range(len(prior_paras)) if i not in used_prior]
    added = [_excerpt(latest_paras[j]) for j in range(len(latest_paras)) if j not in used_latest]
    return added, removed, len(used_prior)
