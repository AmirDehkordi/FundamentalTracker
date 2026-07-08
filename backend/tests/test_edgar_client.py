"""EDGAR client tests: retry/backoff, bronze cache write + offline replay, and throttling.

Hermetic — respx intercepts httpx, no real network, no SEC_USER_AGENT env needed (settings stubbed).
First respx consumer in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from tracker.ingestion import edgar_client

_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
_URL2 = "https://www.sec.gov/files/company_tickers.json"


@pytest.fixture(autouse=True)
def _isolate_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module state per test: fresh client, tmp bronze dir, cache off, stubbed settings."""
    monkeypatch.setattr(edgar_client, "BRONZE_DIR", tmp_path / "bronze")
    monkeypatch.setattr(edgar_client, "from_cache", False)
    monkeypatch.setattr(edgar_client, "_client", None)
    monkeypatch.setattr(edgar_client, "_last_request_ts", None)
    monkeypatch.setattr(
        edgar_client,
        "get_settings",
        lambda: SimpleNamespace(sec_user_agent="Test Agent test@example.com (tests)"),
    )


def test_fetch_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)  # skip real backoff wait
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)  # skip throttle wait
    with respx.mock:
        route = respx.get(_URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
        )
        assert edgar_client.get_json(_URL) == {"ok": True}
        assert route.call_count == 2


def test_fetch_gives_up_after_three_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            edgar_client.get_bytes(_URL)
        assert route.call_count == 3


def test_fetch_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    with respx.mock:
        route = respx.get(_URL).mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
        )
        assert edgar_client.get_json(_URL) == {"ok": True}
        assert route.call_count == 2  # SEC rate-limit (429) is retried


def test_fetch_retries_on_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.sleep", lambda _s: None)
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    with respx.mock:
        route = respx.get(_URL).mock(
            side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})]
        )
        assert edgar_client.get_json(_URL) == {"ok": True}
        assert route.call_count == 2  # transport/timeout is retried


def test_does_not_retry_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            edgar_client.get_bytes(_URL)
        assert route.call_count == 1  # 4xx is permanent — no wasted retries


def test_sends_sec_user_agent_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json={"ok": 1}))
        edgar_client.get_json(_URL)
    # SEC bans requests without a descriptive UA — assert it is actually on the wire.
    assert route.calls.last.request.headers["User-Agent"] == "Test Agent test@example.com (tests)"


def test_get_writes_raw_body_to_bronze(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.time, "sleep", lambda _s: None)
    payload = {"cik": 320193, "entityName": "Apple Inc."}
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        edgar_client.get_json(_URL)
    cached = edgar_client._cache_path(_URL)
    assert cached.exists()
    assert cached.suffix == ".json"  # URL suffix preserved -> deterministic offline lookup
    assert json.loads(cached.read_bytes()) == payload


def test_from_cache_replays_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client, "from_cache", True)
    cached = edgar_client._cache_path(_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b'{"cached": true}')
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json={"net": 1}))
        assert edgar_client.get_json(_URL) == {"cached": True}
        assert route.call_count == 0  # zero network calls on --from-cache


def test_from_cache_missing_file_raises_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client, "from_cache", True)
    with pytest.raises(FileNotFoundError, match="from-cache"):
        edgar_client.get_bytes(_URL)


def test_throttle_spaces_consecutive_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(edgar_client.time, "sleep", lambda s: sleeps.append(s))
    # Pin the clock so the elapsed between the two requests is deterministically zero: the throttle
    # must then sleep the FULL interval. Using the real clock made this flaky on slow CI (Windows),
    # where ~30ms of real work between requests shrank the sleep below the tight tolerance.
    monkeypatch.setattr(edgar_client.time, "monotonic", lambda: 1000.0)
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json={"a": 1}))
        respx.get(_URL2).mock(return_value=httpx.Response(200, json={"b": 2}))
        edgar_client.get_json(_URL)  # first: no prior request -> no wait
        edgar_client.get_json(_URL2)  # second: back-to-back -> throttle sleeps
    positive = [s for s in sleeps if s > 0]
    assert positive, "the back-to-back second request must be throttled"
    # Zero elapsed -> the throttle sleeps exactly the 1/8s ceiling; a wrong interval fails this.
    assert abs(max(positive) - edgar_client._MIN_INTERVAL_S) < 0.02
