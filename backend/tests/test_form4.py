"""Form 4 tests: XML parsing (P/S filter, missing price, malformed + XXE safety), the XSL-prefix
strip, the 12-month window, and batch dedupe. Pure functions — no network, no DB."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tracker.ingestion import form4
from tracker.ingestion.submissions import RecentFiling

_FIXTURES = Path(__file__).parent / "fixtures" / "form4"


def _load(name: str) -> bytes:
    return (_FIXTURES / f"{name}.xml").read_bytes()


def test_parse_keeps_only_buy_sell_and_handles_missing_price() -> None:
    rows = form4.parse_form4_xml(_load("buy_and_sale"), 320193, "acc-1", date(2024, 7, 15))
    assert [r.code for r in rows] == ["P", "S", "P"]  # the M (option exercise) row is dropped
    assert all(r.insider_name == "COOK TIMOTHY D" for r in rows)
    assert all(r.role == "Chief Executive Officer" for r in rows)

    buy, sale, footnote = rows
    assert buy.shares == Decimal("1000.0000") and buy.price == Decimal("150.000000")
    assert buy.value == Decimal("150000.000000")  # shares * price
    assert sale.value == Decimal("400000.000000")
    assert footnote.price is None and footnote.value is None  # footnote-only price -> NULLs


def test_parse_malformed_xml_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        rows = form4.parse_form4_xml(_load("malformed"), 320193, "acc-bad", date(2024, 7, 15))
    assert rows == []
    assert "acc-bad" in caplog.text


def test_parse_xxe_entity_is_not_expanded() -> None:
    # The external SYSTEM entity must not be resolved (no file read/network); the row is dropped.
    rows = form4.parse_form4_xml(_load("xxe"), 320193, "acc-xxe", date(2024, 7, 15))
    assert rows == []


def test_parse_without_reporting_owner_returns_empty() -> None:
    xml = b'<?xml version="1.0"?><ownershipDocument><nonDerivativeTable/></ownershipDocument>'
    assert form4.parse_form4_xml(xml, 1, "acc", date(2024, 1, 1)) == []


def test_parse_skips_transactions_with_missing_or_unparseable_shares() -> None:
    xml = (
        b'<?xml version="1.0"?><ownershipDocument>'
        b"<reportingOwner><reportingOwnerId><rptOwnerName>X Y</rptOwnerName>"
        b"</reportingOwnerId></reportingOwner><nonDerivativeTable>"
        b"<nonDerivativeTransaction>"
        b"<transactionCoding><transactionCode>P</transactionCode></transactionCoding>"
        b"<transactionAmounts><transactionPricePerShare><value>10.00</value>"
        b"</transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>"
        b"<nonDerivativeTransaction>"
        b"<transactionCoding><transactionCode>S</transactionCode></transactionCoding>"
        b"<transactionAmounts><transactionShares><value>not-a-number</value>"
        b"</transactionShares></transactionAmounts></nonDerivativeTransaction>"
        b"</nonDerivativeTable></ownershipDocument>"
    )
    # First row: no shares element; second: unparseable shares -> both skipped, never crash.
    assert form4.parse_form4_xml(xml, 1, "acc", date(2024, 1, 1)) == []


def test_build_insider_txns_skips_a_failing_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [RecentFiling("4", "acc-1", "d.xml", date.today(), None)]

    def _boom(*_a: object, **_k: object) -> bytes:
        raise RuntimeError("network down")

    monkeypatch.setattr(form4, "fetch_form4_xml", _boom)
    result = form4.build_insider_txns(1, records, date.today())
    assert result.txns == []  # per-filing failure skipped
    assert result.capped is False  # one filing, well under the cap


def test_build_insider_txns_flags_capped_history() -> None:
    as_of = date(2025, 1, 1)
    many = [RecentFiling("4", f"a-{i}", "d.xml", date(2024, 12, 1), None) for i in range(250)]
    result = form4.build_insider_txns(1, many, as_of)
    assert result.capped is True  # 250 filings exceed _CAP_PER_COMPANY=200
    assert result.txns == []  # every fetch fails against a fake accession -> no rows, still flagged


def test_raw_xml_name_strips_xsl_wrapper_and_is_noop_otherwise() -> None:
    assert form4.raw_xml_name("xslF345X05/wk-form4.xml") == "wk-form4.xml"
    assert form4.raw_xml_name("xslF345X03/doc_4.xml") == "doc_4.xml"
    assert form4.raw_xml_name("wf-form4.xml") == "wf-form4.xml"  # already raw


def test_select_form4_windows_by_as_of_and_excludes_amendments() -> None:
    as_of = date(2025, 1, 1)  # cutoff = 2024-01-02
    records = [
        RecentFiling("4", "a-1", "d1.xml", date(2024, 12, 1), None),  # inside window
        RecentFiling("4", "a-2", "d2.xml", date(2023, 6, 1), None),  # too old -> excluded
        RecentFiling("4/A", "a-3", "d3.xml", date(2024, 12, 15), None),  # amendment -> excluded
        RecentFiling("10-K", "a-4", "d4.htm", date(2024, 11, 1), date(2024, 9, 30)),  # not a 4
    ]
    selection = form4.select_form4_filings(records, as_of)
    assert [r.accession for r in selection.filings] == ["a-1"]
    assert selection.capped is False


def test_select_form4_caps_per_company() -> None:
    as_of = date(2025, 1, 1)
    many = [RecentFiling("4", f"a-{i}", "d.xml", date(2024, 12, 1), None) for i in range(50)]
    selection = form4.select_form4_filings(many, as_of, cap=40)
    assert len(selection.filings) == 40
    assert selection.capped is True


def test_select_form4_not_capped_when_under_limit() -> None:
    as_of = date(2025, 1, 1)
    few = [RecentFiling("4", f"a-{i}", "d.xml", date(2024, 12, 1), None) for i in range(30)]
    selection = form4.select_form4_filings(few, as_of, cap=40)
    assert len(selection.filings) == 30
    assert selection.capped is False


def test_dedupe_batch_collapses_same_natural_key_last_wins(
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = form4.InsiderTxn(
        cik=1,
        accession="a",
        filed=date(2024, 7, 10),
        insider_name="X",
        role=None,
        code="P",
        shares=Decimal("1000.0000"),
        price=Decimal("150.000000"),
        value=Decimal("150000.000000"),
    )
    dup = base.model_copy(
        update={"price": Decimal("160.000000"), "value": Decimal("160000.000000")}
    )
    with caplog.at_level(logging.WARNING):
        out = form4._dedupe_batch([base, dup])
    assert len(out) == 1  # same (accession, name, code, shares, filed) key collapses...
    assert out[0].price == Decimal("160.000000")  # ...and the last row wins
    assert "collapsing" in caplog.text  # a lossy collapse (different price) is logged loudly


def test_dedupe_batch_silent_for_exact_duplicate() -> None:
    row = form4.InsiderTxn(
        cik=1,
        accession="a",
        filed=date(2024, 7, 10),
        insider_name="X",
        role=None,
        code="S",
        shares=Decimal("10.0000"),
        price=Decimal("5.000000"),
        value=Decimal("50.000000"),
    )
    assert len(form4._dedupe_batch([row, row.model_copy()])) == 1  # identical rows: true dedupe
