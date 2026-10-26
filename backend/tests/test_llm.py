"""The LLM client factory + timed helpers (agent/llm.py). No network; the factory only builds."""

from __future__ import annotations

import pytest

from fixtures.fake_llm import FakeOpenAI, stop_turn
from tracker.agent import llm
from tracker.config import get_settings


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "fake-model")
    monkeypatch.setenv("SEC_USER_AGENT", "Test test@test.co (t)")
    get_settings.cache_clear()
    llm.get_client.cache_clear()
    yield
    get_settings.cache_clear()
    llm.get_client.cache_clear()


def test_get_client_wires_settings() -> None:
    client = llm.get_client()
    assert "fake" in str(client.base_url)
    assert client.api_key == "test-key"
    # get_llm_client is the FastAPI seam over the same cached client.
    assert llm.get_llm_client() is client


def test_timed_helpers_tolerate_missing_usage() -> None:
    # A proxy may omit `usage`; the per-call logging must not raise on it.
    fake = FakeOpenAI([stop_turn(usage=False)])
    resp = llm.call_tools(fake, model="m", messages=[], tools=[])
    assert resp.usage is None
    assert resp.choices[0].message.content == "done"
