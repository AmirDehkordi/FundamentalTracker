"""Filings tests: 10-K item extraction (TOC + cross-reference traps), chunker invariants, and the
submissions parallel-array reader. Pure functions — no network, no DB."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from tracker.ingestion import filings, submissions

_TENK = Path(__file__).parent / "fixtures" / "tenk" / "toc_and_sections.html"
_SUBMISSIONS = Path(__file__).parent / "fixtures" / "submissions" / "aapl.json"


def _fixture_text() -> str:
    return filings.html_to_text(_TENK.read_text())


# --------------------------------------------------------------------------------------------------
# html_to_text
# --------------------------------------------------------------------------------------------------


def test_html_to_text_strips_script_style_and_collapses_nbsp() -> None:
    html = (
        "<html><head><style>.h{color:red}</style>"
        "<script>bad()</script></head>"
        "<body><p>Hello&nbsp;&nbsp;World</p><p>  spaced   out  </p></body></html>"
    )
    text = filings.html_to_text(html)
    assert "bad()" not in text and ".h{color:red}" not in text  # script/style dropped
    assert "Hello World" in text  # nbsp (\xa0) collapsed to a single space
    assert "spaced out" in text  # internal whitespace runs collapsed


# --------------------------------------------------------------------------------------------------
# extract_item — the TOC + cross-reference traps
# --------------------------------------------------------------------------------------------------


def test_item_1a_skips_toc_and_is_bounded_by_item_1b() -> None:
    onea = filings.extract_item(_fixture_text(), "1A")
    # The body span, not the tiny table-of-contents "Item 1A ... 5" line.
    assert "RISK_BODY_START" in onea and "RISK_BODY_END" in onea
    assert len(onea) >= 2000
    # Bounded at Item 1B: MD&A must not leak into the risk-factor section.
    assert "MDNA_BODY_START" not in onea


def test_item_7_is_not_truncated_by_a_see_item_7a_cross_reference() -> None:
    seven = filings.extract_item(_fixture_text(), "7")
    assert "MDNA_BODY_START" in seven
    # The mid-line "see Item 7A" cross-reference must NOT end the section early...
    assert "see Item 7A" in seven
    assert "MDNA_AFTER_XREF" in seven and "MDNA_BODY_END" in seven
    # ...but the real line-anchored Item 7A heading DOES bound it.
    assert "MARKET_RISK_MARKER" not in seven
    assert len(seven) >= 2000


def test_item_7_recovers_mdna_from_titled_section_when_heading_is_a_stub() -> None:
    # ETN/Eaton pattern: the "Item 7" heading is a cross-reference; the MD&A lives under its title.
    body = "Revenue and segment results are discussed in detail here. " * 60  # ~3400 chars
    text = "\n".join(
        [
            "Item 7. Management's Discussion and Analysis ......... 30",  # TOC
            "Item 7A. Quantitative and Qualitative Disclosures ......... 45",
            "Item 7. Management's Discussion and Analysis of Financial Condition.",
            "Information required by this Item is presented in the MD&A section below.",
            "Item 7A. Quantitative and Qualitative Disclosures.",  # adjacent -> stub span < 2000
            "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION.",  # standalone title
            "MDNA_TITLED_MARKER. " + body,
            "Market Risk Disclosure",  # bounds the titled MD&A section
            "Interest rate and currency risk are discussed here.",
        ]
    )
    seven = filings.extract_item(text, "7")
    assert "MDNA_TITLED_MARKER" in seven and len(seven) >= 2000  # recovered the titled MD&A
    assert "Information required by this Item" not in seven  # not the cross-reference stub
    assert "Interest rate and currency risk" not in seven  # bounded at Market Risk Disclosure


def test_mid_line_item_references_are_not_treated_as_headings() -> None:
    # A sentence naming Item 1B / Item 2 mid-line must neither start nor bound a section.
    body = "ANTIBLOWUP " * 300  # ~3300 chars
    text = "\n".join(
        [
            "Item 1A. Risk Factors",
            body,
            "Investors should also review Item 1B and consider Item 2 exposures.",
            "Item 1B. Unresolved Staff Comments",
            "None.",
        ]
    )
    onea = filings.extract_item(text, "1A")
    assert "ANTIBLOWUP" in onea
    assert "Investors should also review" in onea  # mid-line refs did not truncate the span
    assert "None." not in onea  # the real line-anchored Item 1B heading bounds it


def test_extract_item_falls_back_to_item_2_when_item_1b_absent() -> None:
    text = "\n".join(
        ["Item 1A. Risk Factors", "RISKMARK " * 300, "Item 2. Properties", "We own facilities."]
    )
    onea = filings.extract_item(text, "1A")
    assert "RISKMARK" in onea
    assert "We own facilities." not in onea  # fallback boundary Item 2 bounds it


def test_extract_item_rejects_unsupported_item() -> None:
    with pytest.raises(ValueError, match="unsupported item"):
        filings.extract_item("text", "9Z")


# --------------------------------------------------------------------------------------------------
# _extract_items — FULL fallback and single-item selection
# --------------------------------------------------------------------------------------------------


def test_extract_items_falls_back_to_full_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    text = "A short annual report with no recognizable item headings at all."
    with caplog.at_level(logging.WARNING):
        items = filings._extract_items(text, "AAPL", "acc-1")
    assert set(items) == {"FULL"}
    assert items["FULL"] == text
    assert "AAPL" in caplog.text and "FULL" in caplog.text


def test_extract_items_keeps_only_the_section_over_the_floor() -> None:
    text = "\n".join(["Item 1A. Risk Factors", "word " * 500, "Item 1B. Unresolved Comments"])
    items = filings._extract_items(text, "AAPL", "acc-1")
    assert set(items) == {"1A"}  # no Item 7 in the doc -> only 1A crosses the length floor


# --------------------------------------------------------------------------------------------------
# chunk — invariants
# --------------------------------------------------------------------------------------------------


def test_chunk_rejects_bad_size_overlap() -> None:
    with pytest.raises(ValueError):
        filings.chunk("abc", size=100, overlap=60)  # size not > 2*overlap
    with pytest.raises(ValueError):
        filings.chunk("abc", size=100, overlap=100)  # overlap not < size


def test_chunk_empty_and_single() -> None:
    assert filings.chunk("") == []
    assert filings.chunk("   \n  ") == []  # whitespace-only -> no empty chunk row
    assert filings.chunk("short text") == ["short text"]


def test_chunk_invariants_on_paragraphed_text() -> None:
    para = "Sentence about company operations and outlook. " * 20  # ~940 chars, no newline inside
    text = "\n".join([para] * 8)  # ~7500 chars with paragraph boundaries
    size, overlap = filings._CHUNK_SIZE, filings._CHUNK_OVERLAP

    chunks = filings.chunk(text)
    assert len(chunks) > 1
    assert all(len(c) <= size for c in chunks)  # I4 size bound

    reconstructed = chunks[0]
    for prev, cur in zip(chunks, chunks[1:], strict=False):  # pairwise; slices differ by one
        assert prev[-overlap:] == cur[:overlap]  # I3 exact overlap boundary
        reconstructed += cur[overlap:]
    assert reconstructed == text  # I2 no dropped characters


def test_chunk_terminates_on_adversarial_no_newline_input() -> None:
    text = "x" * 5000  # no break points anywhere -> must hard-cut, never hang
    chunks = filings.chunk(text)
    assert all(len(c) <= filings._CHUNK_SIZE for c in chunks)
    assert "".join([chunks[0]] + [c[filings._CHUNK_OVERLAP :] for c in chunks[1:]]) == text
    assert len(chunks) < 10  # bounded


# --------------------------------------------------------------------------------------------------
# submissions + select_recent_10ks
# --------------------------------------------------------------------------------------------------


def test_recent_filings_parses_dates_and_empty_report_date() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "4"],
                "accessionNumber": ["a-1", "a-2"],
                "primaryDocument": ["d1.htm", "d2.xml"],
                "filingDate": ["2024-11-01", "2024-07-15"],
                "reportDate": ["2024-09-28", ""],
            }
        }
    }
    rows = submissions.recent_filings(payload)
    assert [r.form for r in rows] == ["10-K", "4"]
    assert rows[0].report_date == date(2024, 9, 28)
    assert rows[1].report_date is None  # empty reportDate -> None, row still kept
    assert rows[0].filing_date == date(2024, 11, 1)


def test_recent_filings_truncates_ragged_arrays_and_skips_bad_dates() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "4", "8-K"],  # one longer than the rest -> ragged
                "accessionNumber": ["a-1", "a-2"],
                "primaryDocument": ["d1", "d2"],
                "filingDate": ["not-a-date", "2024-02-02"],
                "reportDate": ["2023-12-31", ""],
            }
        }
    }
    rows = submissions.recent_filings(payload)
    assert len(rows) == 1  # ragged -> truncated to 2, bad filingDate row skipped
    assert rows[0].accession == "a-2"


def test_select_recent_10ks_picks_two_newest_and_excludes_amendments() -> None:
    records = submissions.recent_filings(json.loads(_SUBMISSIONS.read_text()))
    tenks = filings.select_recent_10ks(records)
    assert [t.accession for t in tenks] == ["0000320193-24-000123", "0000320193-23-000106"]
    assert all(t.form == "10-K" for t in tenks)  # 10-K/A amendment excluded
    assert filings.select_recent_10ks(records, limit=1)[0].accession == "0000320193-24-000123"


def test_select_recent_10ks_skips_missing_report_date() -> None:
    records = [
        submissions.RecentFiling("10-K", "acc-1", "d.htm", date(2024, 11, 1), None),
        submissions.RecentFiling("10-K", "acc-2", "d.htm", date(2023, 11, 3), date(2023, 9, 30)),
    ]
    tenks = filings.select_recent_10ks(records)
    assert [t.accession for t in tenks] == ["acc-2"]  # acc-1 dropped: no reportDate
