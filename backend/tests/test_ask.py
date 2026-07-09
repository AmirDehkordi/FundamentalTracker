"""POST /api/ask end to end (api/routers/ask.py): TestClient + overridden session and LLM client."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fixtures.fake_llm import FakeOpenAI, final_response, stop_turn, tool_call, tool_response
from tracker.agent.llm import get_llm_client
from tracker.api.app import create_app
from tracker.api.routers.ask import get_session_factory
from tracker.config import get_settings

_CIT = {
    "source_type": "fundamental",
    "ticker": "AAPL",
    "fiscal_year": 2025,
    "accession": "0000320193-2025-10K",
    "detail": "Trailing P/E 25.6, FY2025",
}


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@test.co (t)")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client(session: Session, fake: FakeOpenAI) -> TestClient:
    app = create_app()
    # The worker calls the factory to get a session; hand it the seeded one (its .close() on the
    # shared in-memory session is harmless — StaticPool keeps the data for the fixture teardown).
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    app.dependency_overrides[get_llm_client] = lambda: fake
    return TestClient(app)


def test_ask_happy_path(db_session: Session) -> None:
    fake = FakeOpenAI(
        [
            tool_response(tool_call("c1", "get_valuation", {"ticker": "AAPL"})),
            stop_turn(),
            final_response({"answer_md": "AAPL P/E is 25.6 for FY2025.", "citations": [_CIT]}),
        ]
    )
    resp = _client(db_session, fake).post("/api/ask", json={"question": "AAPL P/E?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["declined"] is False
    assert body["citations"][0]["ticker"] == "AAPL"
    assert [t["tool"] for t in body["trace"]] == ["get_valuation"]


def test_ask_refusal_path(db_session: Session) -> None:
    fake = FakeOpenAI(
        [
            stop_turn(),
            final_response(
                {
                    "answer_md": "Out of scope.",
                    "declined": True,
                    "decline_reason": "The tracker holds reported historicals only.",
                }
            ),
        ]
    )
    resp = _client(db_session, fake).post(
        "/api/ask", json={"question": "What will AAPL earn next year?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["declined"] is True
    assert body["decline_reason"] == "The tracker holds reported historicals only."


def test_ask_times_out_declines_not_500(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tracker.api.routers import ask as ask_module

    monkeypatch.setattr(ask_module, "_TIMEOUT_S", 0.05)

    def _slow(*_a: object, **_k: object) -> None:
        time.sleep(0.3)  # exceeds the patched hard timeout; worker returns after we've responded

    monkeypatch.setattr(ask_module.loop, "run", _slow)
    resp = _client(db_session, FakeOpenAI([])).post("/api/ask", json={"question": "q"})
    assert resp.status_code == 200
    assert resp.json()["decline_reason"] == "timeout"


def test_ask_internal_error_declines_not_500(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tracker.api.routers import ask as ask_module

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(ask_module.loop, "run", _boom)
    resp = _client(db_session, FakeOpenAI([])).post("/api/ask", json={"question": "q"})
    assert resp.status_code == 200
    assert resp.json()["decline_reason"] == "internal error"


def test_ask_oversized_question_declined(db_session: Session) -> None:
    # Guarded before any LLM call, so the empty fake is never touched.
    resp = _client(db_session, FakeOpenAI([])).post("/api/ask", json={"question": "x" * 5000})
    assert resp.status_code == 200
    assert resp.json()["decline_reason"] == "request too large"


def test_ask_oversized_history_declined(db_session: Session) -> None:
    history = [{"role": "user", "content": "h"} for _ in range(21)]  # > _MAX_HISTORY_TURNS
    resp = _client(db_session, FakeOpenAI([])).post(
        "/api/ask", json={"question": "q", "history": history}
    )
    assert resp.status_code == 200
    assert resp.json()["decline_reason"] == "request too large"


def test_get_session_factory_is_the_real_sessionmaker() -> None:
    from sqlalchemy.orm import sessionmaker

    assert isinstance(get_session_factory(), sessionmaker)  # the production DI provider
