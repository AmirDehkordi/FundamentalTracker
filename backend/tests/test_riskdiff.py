"""Deterministic Item 1A diff (services/riskdiff.py) — synthetic paragraphs, no LLM."""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from tracker.api import schemas
from tracker.db.models import FilingChunk
from tracker.services import riskdiff

AAPL_CIK = 320193
NVDA_CIK = 1045810
NVDA_2024 = "0001045810-2024-10K"
NVDA_2025 = "0001045810-2025-10K"

# Paragraphs are >120 chars: the de-noise filter drops sub-sentence fragments (headers, captions,
# page furniture) that reflowed year over year and inflated the diff, so real risk factors must read
# like real risk factors.
COMMON = (
    "The company faces competition in the semiconductor market from larger rivals with greater "
    "scale, and competitive pressure could erode our pricing and market share over time materially."
)
REMOVED = (
    "Supply chain constraints for advanced packaging and capacity could limit our ability to meet "
    "customer demand and delay shipments of our most advanced products during the coming period."
)
ADDED = (
    "New and expanded export control regulations may restrict sales of our most advanced chips and "
    "related technology to important markets abroad, which could materially reduce our revenue."
)
REWORD_OLD = (
    "Our business depends on a few large customers, and the loss of any one of them accounting for "
    "a significant share of revenue would materially harm our results of operations and cash flows."
)
REWORD_NEW = (
    "Our business depends on a few large customers, and the loss of any one of them accounting for "
    "a significant portion of revenue would materially harm our results of operations and cash "
    "flows."
)


def _chunks(session: Session, cik: int, accession: str, fiscal_year: int, texts: list[str]) -> None:
    for idx, text in enumerate(texts):
        session.add(
            FilingChunk(
                accession=accession,
                cik=cik,
                item="1A",
                fiscal_year=fiscal_year,
                chunk_index=idx,
                text=text,
            )
        )


def test_riskdiff_added_removed_and_unchanged(db_session: Session) -> None:
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [COMMON, REMOVED, REWORD_OLD])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [COMMON, ADDED, REWORD_NEW])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.available is True
    assert result.counts.unchanged == 2  # COMMON + the high-similarity reword
    assert result.counts.added == 1
    assert result.counts.removed == 1
    assert any("export control" in a for a in result.added)
    assert any("advanced packaging" in r for r in result.removed)


def test_riskdiff_greedy_keeps_best_of_near_duplicates(db_session: Session) -> None:
    # Two prior paragraphs both similar to one latest paragraph: the best (exact) match is kept, the
    # other is skipped (already-used) and falls to `removed`. Their ~0.8 similarity stays below the
    # 0.97 intra-year merge threshold, so they are not collapsed before pairing.
    latest = (
        "Our supply chain faces constraints on advanced packaging capacity, which could limit our "
        "output and delay shipments of flagship data-center accelerators during strong demand."
    )
    near_dup = (
        "Our supply chain faces constraints on advanced packaging and additional final-test "
        "capacity, which could limit output and delay shipments of flagship data-center parts."
    )
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [latest, near_dup])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [latest])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.counts.unchanged == 1  # the exact match is paired
    assert result.counts.removed == 1  # the near-duplicate is skipped -> removed
    assert result.added == []


def test_riskdiff_pairing_is_not_positional(db_session: Session) -> None:
    para_a = (
        "Risk A concerns data-center demand cycles and the inventory build that accompanies them, "
        "which could leave us exposed to a sudden slowdown in hyperscaler capital spending."
    )
    para_b = (
        "Risk B concerns foreign exchange rate volatility and the effectiveness of our hedging "
        "program, which may not fully offset the impact of a strengthening dollar on our results."
    )
    para_c = (
        "Risk C concerns litigation and regulatory penalties across multiple regions, any of which "
        "could result in significant fines, injunctions, or restrictions on how we operate."
    )
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [para_a, para_b, para_c])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [para_c, para_a, para_b])  # reordered
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.counts.unchanged == 3
    assert result.added == []
    assert result.removed == []


def test_riskdiff_excerpt_capped_at_240(db_session: Session) -> None:
    long_para = "word " * 80  # 400 chars, unmatched -> lands in `added`
    prior = (
        "A prior risk paragraph about litigation exposure and regulatory penalties, written to be "
        "clearly different from the added paragraph so the two never pair as unchanged this year."
    )
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [prior])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [long_para])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.added
    assert all(len(a) <= 240 for a in result.added)


def test_riskdiff_drops_page_furniture(db_session: Session) -> None:
    # Page numbers, section headers and short fragments must NOT surface as diff lines.
    real = (
        "Our results depend on the continued availability of advanced foundry capacity, and any "
        "disruption at a key supplier could materially reduce the volume of chips we can ship."
    )
    prior_noise = ["42", "Table of Contents", "Item 1A. Risk Factors", "See page 17.", real]
    latest_noise = ["43", "PART I", "Item 1A.", real]
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, prior_noise)
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, latest_noise)
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    # Only the one real paragraph survives, and it is unchanged -> zero added / removed noise.
    assert result.counts.unchanged == 1
    assert result.counts.added == 0 and result.counts.removed == 0


def test_riskdiff_keeps_prose_that_opens_with_digits(db_session: Session) -> None:
    # A real risk factor that merely BEGINS with digits ("9/11-type…", "1/3 of revenue…") must not
    # be mistaken for page furniture and dropped — the page-number filter matches bare numbers only.
    prior = (
        "9/11-type catastrophic events, pandemics, and geopolitical conflict could disrupt our "
        "global supply chain and materially reduce demand for our products across every segment."
    )
    latest = (
        "1/3 of our revenue comes from a single hyperscale customer, and the loss of that customer "
        "would materially and adversely affect our results of operations and our overall outlook."
    )
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [prior])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [latest])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert any("9/11" in r for r in result.removed)  # survived the filter
    assert any("1/3" in a for a in result.added)


def test_riskdiff_reconstruction_dedupes_overlap(db_session: Session) -> None:
    p1 = (
        "Paragraph one concerns market competition from established and emerging rivals, and the "
        "risk that price competition could compress our gross margins over successive quarters."
    )
    p2 = (
        "Paragraph two concerns supply chain and logistics disruptions, including port congestion "
        "and component shortages that could delay our ability to fulfil customer orders on time."
    )
    p3 = (
        "Paragraph three concerns new regulation of artificial intelligence and export controls, "
        "which could restrict the markets we serve and increase our cost of compliance materially."
    )
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [p1, p2, p3])
    # Latest FY split into two chunks whose boundary repeats p2 (the ~200-char overlap).
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [f"{p1}\n\n{p2}", f"{p2}\n\n{p3}"])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.counts.unchanged == 3  # p2 counted once, not twice
    assert result.added == []


def test_riskdiff_filing_refs(db_session: Session) -> None:
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [REMOVED])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [ADDED])
    db_session.commit()

    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    assert result.latest is not None and result.prior is not None
    assert result.latest.fiscal_year == 2025
    assert result.latest.period_end == datetime.date(2025, 1, 25)
    assert result.latest.accession == NVDA_2025
    assert result.latest.primary_doc_url.endswith(f"{NVDA_2025}.htm")
    assert result.latest.label == "FY2025 (ended 2025-01-25)"
    assert result.prior.fiscal_year == 2024


def test_riskdiff_degraded_single_fiscal_year(db_session: Session) -> None:
    # mini_seed gives AAPL exactly one FY of 1A chunks -> not enough to diff.
    result = riskdiff.diff_risk_factors(db_session, AAPL_CIK)
    assert result.available is False
    assert result.note == riskdiff.RISKDIFF_UNAVAILABLE_NOTE
    assert result.latest is not None and result.latest.fiscal_year == 2025
    assert result.prior is None
    assert result.added == [] and result.removed == []
    assert result.counts.unchanged == 0


def test_riskdiff_degraded_no_chunks(db_session: Session) -> None:
    result = riskdiff.diff_risk_factors(db_session, NVDA_CIK)  # NVDA has no seeded chunks
    assert result.available is False
    assert result.latest is None and result.prior is None


def test_riskdiff_degraded_when_filing_missing(db_session: Session) -> None:
    # Chunks whose accession has no parent filing (SQLite does not enforce the FK) -> degraded.
    _chunks(db_session, 777, "nofil-2024", 2024, ["prior risk"])
    _chunks(db_session, 777, "nofil-2025", 2025, ["latest risk"])
    db_session.commit()
    result = riskdiff.diff_risk_factors(db_session, 777)
    assert result.available is False
    assert result.latest is None


def test_riskdiff_maps_to_wire_schema(db_session: Session) -> None:
    _chunks(db_session, NVDA_CIK, NVDA_2024, 2024, [REMOVED])
    _chunks(db_session, NVDA_CIK, NVDA_2025, 2025, [ADDED])
    db_session.commit()
    wire = schemas.RiskDiffOut.model_validate(riskdiff.diff_risk_factors(db_session, NVDA_CIK))
    assert wire.available is True
    assert wire.latest is not None and wire.latest.fiscal_year == 2025


def test_riskdiff_degraded_maps_to_wire_schema(db_session: Session) -> None:
    # The degraded card is a real feature (§13): its None refs must survive model_validate.
    wire = schemas.RiskDiffOut.model_validate(riskdiff.diff_risk_factors(db_session, NVDA_CIK))
    assert wire.available is False
    assert wire.latest is None and wire.prior is None
