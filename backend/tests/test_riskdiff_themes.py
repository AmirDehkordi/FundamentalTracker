"""Risk-theme clustering pipeline (agent/riskdiff_themes.py) — the scripted FakeOpenAI client only,
never a real LLM. Distinct from test_risk_diff_summary.py's top-3-item module, which is untouched.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fixtures.fake_llm import FakeOpenAI, final_response
from tracker.agent import riskdiff_themes
from tracker.api.app import create_app
from tracker.api.deps import optional_llm_client
from tracker.db.models import FilingChunk
from tracker.db.session import get_session
from tracker.services import risk_theme_cache as cache
from tracker.services import riskdiff
from tracker.services.riskdiff import FilingRefData, RiskDiffResult

NVDA_CIK = 1045810
LATEST = "0001045810-2025-10K"
PRIOR = "0001045810-2024-10K"
_MODEL = "fake-model"

_ADDED_1 = (
    "New and expanded export control regulations may restrict sales of our most advanced chips "
    "and related technology to important markets abroad, which could materially reduce revenue."
)
_ADDED_2 = (
    "Emerging tariffs on semiconductor imports could increase our production costs and compress "
    "margins across our data center and gaming product lines going forward this fiscal year."
)
_REMOVED_1 = (
    "Supply chain constraints for advanced packaging and capacity could limit our ability to meet "
    "customer demand and delay shipments of our most advanced products during the coming period."
)

_DRAFT = {
    "added": [
        {
            "title": "Export controls tighten",
            "summary": "New rules restrict chip sales abroad.",
            "excerpt_indices": [0],
        },
        {
            "title": "Tariffs raise costs",
            "summary": "New tariffs compress margins.",
            "excerpt_indices": [1],
        },
    ],
    "removed": [
        {
            "title": "Packaging supply eases",
            "summary": "Advanced-packaging constraints no longer flagged.",
            "excerpt_indices": [0],
        },
    ],
}


def _diff(added: list[str], removed: list[str], *, available: bool = True) -> RiskDiffResult:
    if not available:
        return RiskDiffResult(
            ticker="NVDA",
            cik=NVDA_CIK,
            item="1A",
            latest=None,
            prior=None,
            added=[],
            removed=[],
            counts=riskdiff.RiskDiffCountsData(added=0, removed=0, unchanged=0),
            available=False,
            note=riskdiff.RISKDIFF_UNAVAILABLE_NOTE,
        )
    latest_ref = FilingRefData(
        fiscal_year=2025,
        period_end=date(2025, 1, 25),
        accession=LATEST,
        primary_doc_url="https://www.sec.gov/x",
        label="FY2025",
    )
    prior_ref = FilingRefData(
        fiscal_year=2024,
        period_end=date(2024, 1, 25),
        accession=PRIOR,
        primary_doc_url="https://www.sec.gov/y",
        label="FY2024",
    )
    return RiskDiffResult(
        ticker="NVDA",
        cik=NVDA_CIK,
        item="1A",
        latest=latest_ref,
        prior=prior_ref,
        added=added,
        removed=removed,
        counts=riskdiff.RiskDiffCountsData(added=len(added), removed=len(removed), unchanged=0),
        available=True,
        note=None,
    )


def _happy_client() -> FakeOpenAI:
    return FakeOpenAI([final_response(_DRAFT), final_response(_DRAFT), final_response(_DRAFT)])


# --- happy path / pipeline shape ------------------------------------------------------------------


def test_happy_path_runs_all_three_stages(db_session: Session) -> None:
    diff = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])
    client = _happy_client()
    result = riskdiff_themes.get_or_build_themes(db_session, client, _MODEL, diff)
    assert result.available is True
    assert len(client.calls) == 3
    assert [t.title for t in result.added_themes] == [
        "Export controls tighten",
        "Tariffs raise costs",
    ]
    assert result.removed_themes[0].paragraph_count == 1


def test_degraded_diff_skips_llm(db_session: Session) -> None:
    diff = _diff([], [], available=False)
    client = FakeOpenAI([])
    result = riskdiff_themes.get_or_build_themes(db_session, client, _MODEL, diff)
    assert result.available is False
    assert result.added_themes == [] and result.removed_themes == []
    assert result.note == riskdiff.RISKDIFF_UNAVAILABLE_NOTE
    assert len(client.calls) == 0


def test_both_sides_empty_short_circuits(db_session: Session) -> None:
    diff = _diff([], [])  # available=True, two FYs exist, but nothing changed after denoise
    client = FakeOpenAI([])
    result = riskdiff_themes.get_or_build_themes(db_session, client, _MODEL, diff)
    assert result.available is True
    assert result.added_themes == [] and result.removed_themes == []
    assert len(client.calls) == 0
    # nothing was persisted either — direct cache check confirms a true miss, not a cached-empty row
    h = cache.content_hash([], [])
    assert cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h) is None


# --- DB-backed caching -------------------------------------------------------------------------


def test_second_call_same_session_hits_db_cache_not_llm(db_session: Session) -> None:
    diff = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])
    first = riskdiff_themes.get_or_build_themes(db_session, _happy_client(), _MODEL, diff)

    empty_client = FakeOpenAI([])  # any call raises AssertionError — proves this is a DB cache hit
    second = riskdiff_themes.get_or_build_themes(db_session, empty_client, _MODEL, diff)

    assert second == first
    assert len(empty_client.calls) == 0


def test_cache_hit_serves_with_no_llm_configured(db_session: Session) -> None:
    diff = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])
    riskdiff_themes.get_or_build_themes(db_session, _happy_client(), _MODEL, diff)

    result = riskdiff_themes.get_or_build_themes(db_session, None, _MODEL, diff)
    assert result.available is True
    assert len(result.added_themes) == 2


def test_cache_miss_with_no_llm_configured_raises(db_session: Session) -> None:
    diff = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])
    with pytest.raises(riskdiff_themes.RiskThemesUnavailable):
        riskdiff_themes.get_or_build_themes(db_session, None, _MODEL, diff)


def test_cache_invalidates_when_diff_content_changes(db_session: Session) -> None:
    diff_a = _diff([_ADDED_1], [_REMOVED_1])
    riskdiff_themes.get_or_build_themes(db_session, _happy_client(), _MODEL, diff_a)

    # Same accession pair, different excerpt content (as if riskdiff.py's algorithm changed output).
    diff_b = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])
    client_b = _happy_client()
    riskdiff_themes.get_or_build_themes(db_session, client_b, _MODEL, diff_b)
    assert len(client_b.calls) == 3  # stale cache correctly triggered a full regeneration


# --- grounding / content-loss guards -------------------------------------------------------------


def test_out_of_range_theme_is_dropped_not_the_whole_side(db_session: Session) -> None:
    finalize_payload = {
        "added": [
            {
                "title": "Valid theme",
                "summary": "Grounded in real excerpts.",
                "excerpt_indices": [0, 1],
            },
            {
                "title": "Hallucinated theme",
                "summary": "Cites nothing real.",
                "excerpt_indices": [5],
            },
        ],
        "removed": [],
    }
    client = FakeOpenAI(
        [final_response(_DRAFT), final_response(_DRAFT), final_response(finalize_payload)]
    )
    diff = _diff([_ADDED_1, _ADDED_2], [])
    result = riskdiff_themes.get_or_build_themes(db_session, client, _MODEL, diff)
    assert len(result.added_themes) == 1
    assert result.added_themes[0].title == "Valid theme"


def test_all_themes_ungrounded_raises_and_preserves_prior_cache(db_session: Session) -> None:
    diff_a = _diff([_ADDED_1], [_REMOVED_1])
    good = riskdiff_themes.get_or_build_themes(db_session, _happy_client(), _MODEL, diff_a)
    h_a = cache.content_hash(diff_a.added, diff_a.removed)

    diff_b = _diff([_ADDED_1, _ADDED_2], [_REMOVED_1])  # different content -> different hash
    all_bad = {
        "added": [{"title": "Bad", "summary": "Cites nothing real.", "excerpt_indices": [99]}],
        "removed": [{"title": "Fine", "summary": "Real citation.", "excerpt_indices": [0]}],
    }
    client_b = FakeOpenAI([final_response(_DRAFT), final_response(_DRAFT), final_response(all_bad)])
    with pytest.raises(riskdiff_themes.RiskThemesUnavailable):
        riskdiff_themes.get_or_build_themes(db_session, client_b, _MODEL, diff_b)

    # the earlier, good cache entry for diff_a's hash is untouched
    still_cached = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h_a)
    assert still_cached is not None
    assert [c.title for c in still_cached if c.direction == "added"] == [
        t.title for t in good.added_themes
    ]


# --- endpoint ---------------------------------------------------------------------------------


def _seed_two_years(session: Session) -> None:
    for accession, fy, text in ((PRIOR, 2024, _REMOVED_1), (LATEST, 2025, _ADDED_1)):
        session.add(
            FilingChunk(
                accession=accession,
                cik=NVDA_CIK,
                item="1A",
                fiscal_year=fy,
                chunk_index=0,
                text=text,
            )
        )
    session.commit()


def _client(session: Session, client: FakeOpenAI | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[optional_llm_client] = lambda: client
    return TestClient(app)


def test_endpoint_happy_path(db_session: Session) -> None:
    _seed_two_years(db_session)
    resp = _client(db_session, _happy_client()).get("/api/companies/NVDA/risk-diff/themes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["added_themes"][0]["title"] == "Export controls tighten"
    assert body["latest"]["fiscal_year"] == 2025


def test_endpoint_degraded_is_200(db_session: Session) -> None:
    # mini_seed gives AAPL one FY of 1A chunks -> no pair -> degraded, no LLM call, still 200.
    resp = _client(db_session, FakeOpenAI([])).get("/api/companies/AAPL/risk-diff/themes")
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_endpoint_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session, FakeOpenAI([])).get("/api/companies/ZZZZ/risk-diff/themes")
    assert resp.status_code == 404


def test_endpoint_503_when_no_llm_and_no_cache(db_session: Session) -> None:
    _seed_two_years(db_session)
    resp = _client(db_session, None).get("/api/companies/NVDA/risk-diff/themes")
    assert resp.status_code == 503


def test_endpoint_200_from_cache_with_no_llm(db_session: Session) -> None:
    _seed_two_years(db_session)
    warm = _client(db_session, _happy_client())
    assert warm.get("/api/companies/NVDA/risk-diff/themes").status_code == 200

    cold = _client(db_session, None)
    resp = cold.get("/api/companies/NVDA/risk-diff/themes")
    assert resp.status_code == 200
    assert resp.json()["available"] is True
