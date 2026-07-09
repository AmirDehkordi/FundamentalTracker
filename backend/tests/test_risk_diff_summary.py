"""LLM summary of the deterministic Item 1A diff — agent/riskdiff_summary.py + its endpoint.

CI-safe: the scripted FakeOpenAI client only, never a real LLM. Covers the happy path, the one
schema retry, the in-process cache, the degraded (no-pair) state, and the 503 / no-LLM paths.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fixtures.fake_llm import FakeOpenAI, final_response, raw_final
from tracker.agent import llm, riskdiff_summary
from tracker.api.app import create_app
from tracker.api.deps import require_llm_client
from tracker.db.models import FilingChunk
from tracker.db.session import get_session
from tracker.services import riskdiff
from tracker.services.riskdiff import RiskDiffResult

NVDA_CIK = 1045810
NVDA_2024 = "0001045810-2024-10K"
NVDA_2025 = "0001045810-2025-10K"
_MODEL = "fake-model"

_ADDED = (
    "New and expanded export control regulations may restrict sales of our most advanced chips and "
    "related technology to important markets abroad, which could materially reduce our revenue."
)
_REMOVED = (
    "Supply chain constraints for advanced packaging and capacity could limit our ability to meet "
    "customer demand and delay shipments of our most advanced products during the coming period."
)

_PAYLOAD = {
    "added": [
        {
            "title": "Export controls tighten",
            "detail": "New rules may block advanced-chip sales abroad.",
        }
    ],
    "removed": [
        {
            "title": "Packaging supply eases",
            "detail": "Advanced-packaging capacity constraints no longer flagged.",
        }
    ],
}


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    riskdiff_summary.clear_cache()
    yield
    riskdiff_summary.clear_cache()


def _seed_two_years(session: Session) -> None:
    for accession, fy, text in (
        (NVDA_2024, 2024, _REMOVED),
        (NVDA_2025, 2025, _ADDED),
    ):
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


def _client(session: Session, fake: FakeOpenAI | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    if fake is not None:
        app.dependency_overrides[require_llm_client] = lambda: fake
    return TestClient(app)


# --- build_summary (module) ---------------------------------------------------------------------


def test_build_summary_happy_path(db_session: Session) -> None:
    _seed_two_years(db_session)
    diff = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    client = FakeOpenAI([final_response(_PAYLOAD)])
    result = riskdiff_summary.build_summary(client, _MODEL, diff)
    assert result.available is True
    assert result.new_risks[0].title == "Export controls tighten"
    assert result.reduced_risks[0].title == "Packaging supply eases"
    assert len(client.calls) == 1


def test_build_summary_word_caps_truncate(db_session: Session) -> None:
    _seed_two_years(db_session)
    diff = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    long_title = " ".join(["word"] * 20)  # > 8 words
    long_detail = " ".join(["detail"] * 40)  # > 25 words
    client = FakeOpenAI(
        [final_response({"added": [{"title": long_title, "detail": long_detail}], "removed": []})]
    )
    result = riskdiff_summary.build_summary(client, _MODEL, diff)
    assert len(result.new_risks[0].title.split()) == 8
    assert len(result.new_risks[0].detail.split()) == 25


def test_build_summary_retries_once_on_schema_failure(db_session: Session) -> None:
    _seed_two_years(db_session)
    diff = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    client = FakeOpenAI([raw_final("not json at all"), final_response(_PAYLOAD)])
    result = riskdiff_summary.build_summary(client, _MODEL, diff)
    assert result.new_risks and len(client.calls) == 2  # first invalid -> retried -> valid


def test_build_summary_raises_after_two_schema_failures(db_session: Session) -> None:
    _seed_two_years(db_session)
    diff = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    client = FakeOpenAI([raw_final("nope"), raw_final("still nope")])
    with pytest.raises(riskdiff_summary.RiskSummaryUnavailable):
        riskdiff_summary.build_summary(client, _MODEL, diff)


def test_build_summary_caches_per_fy_pair(db_session: Session) -> None:
    _seed_two_years(db_session)
    diff = riskdiff.diff_risk_factors(db_session, NVDA_CIK)
    client = FakeOpenAI([final_response(_PAYLOAD)])  # exactly ONE response scripted
    first = riskdiff_summary.build_summary(client, _MODEL, diff)
    second = riskdiff_summary.build_summary(client, _MODEL, diff)  # must NOT call the LLM again
    assert first == second
    assert len(client.calls) == 1  # the second call was a cache hit


def test_build_summary_degraded_skips_llm() -> None:
    degraded = RiskDiffResult(
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
    client = FakeOpenAI([])  # no responses — the LLM must not be called
    result = riskdiff_summary.build_summary(client, _MODEL, degraded)
    assert result.available is False and result.new_risks == [] and result.reduced_risks == []
    assert result.note == riskdiff.RISKDIFF_UNAVAILABLE_NOTE
    assert len(client.calls) == 0


# --- endpoint -----------------------------------------------------------------------------------


def test_endpoint_happy_path(db_session: Session) -> None:
    _seed_two_years(db_session)
    resp = _client(db_session, FakeOpenAI([final_response(_PAYLOAD)])).get(
        "/api/companies/NVDA/risk-diff/summary"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["new_risks"][0]["title"] == "Export controls tighten"
    assert body["latest"]["fiscal_year"] == 2025


def test_endpoint_degraded_is_200(db_session: Session) -> None:
    # mini_seed gives AAPL one FY of 1A chunks -> no pair -> degraded, no LLM call, still 200.
    resp = _client(db_session, FakeOpenAI([])).get("/api/companies/AAPL/risk-diff/summary")
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_endpoint_unknown_ticker_404(db_session: Session) -> None:
    resp = _client(db_session, FakeOpenAI([])).get("/api/companies/ZZZZ/risk-diff/summary")
    assert resp.status_code == 404


def test_endpoint_503_when_no_llm_configured(db_session: Session, monkeypatch) -> None:
    _seed_two_years(db_session)
    monkeypatch.setattr(llm, "llm_configured", lambda: False)
    resp = _client(db_session, fake=None).get("/api/companies/NVDA/risk-diff/summary")  # real dep
    assert resp.status_code == 503
    assert "LLM" in resp.json()["detail"] or "configured" in resp.json()["detail"].lower()


def test_endpoint_503_on_summary_failure(db_session: Session) -> None:
    _seed_two_years(db_session)
    resp = _client(db_session, FakeOpenAI([raw_final("bad"), raw_final("bad")])).get(
        "/api/companies/NVDA/risk-diff/summary"
    )
    assert resp.status_code == 503
