"""Shared SEC EDGAR HTTP client — the ONLY outbound network path for XBRL ingestion.

Enforces SEC etiquette on every request (sec-edgar skill): the SEC_USER_AGENT header, a global
<= 8 req/s throttle, and tenacity retries on 429/5xx/timeouts. Every response is mirrored to
seed/bronze/ so a `--from-cache` run replays the exact bytes offline with zero network. One
structured log line per GET: url, status, cache_hit, elapsed_ms.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from tracker.config import get_settings

logger = logging.getLogger(__name__)

# Repo-root/seed/bronze. parents: [0]=ingestion [1]=tracker [2]=src [3]=backend [4]=repo root.
# Module attribute (not a constant baked into calls) so tests can redirect it at a tmp dir.
BRONZE_DIR = Path(__file__).resolve().parents[4] / "seed" / "bronze"

# Offline switch — the runner flips this for `--from-cache`. When true, get_* read the mirrored
# bronze file and never touch the network (and raise if a file is missing).
from_cache = False

# SEC allows <= 10 req/s; we self-limit to 8. Fixed minimum spacing between network requests.
_MIN_INTERVAL_S = 1.0 / 8.0
_MAX_ATTEMPTS = 3
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_client: httpx.Client | None = None
_last_request_ts: float | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": get_settings().sec_user_agent},
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
    return _client


def _throttle() -> None:
    """Hold the global <= 8 req/s ceiling by spacing consecutive network requests."""
    global _last_request_ts
    if _last_request_ts is not None:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
    _last_request_ts = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    # Timeouts and connect/read failures are transient; among HTTP statuses only 429 + 5xx are
    # worth retrying (other 4xx are permanent client errors — retrying just wastes SEC's budget).
    if isinstance(exc, httpx.TransportError):  # base class also covers httpx.TimeoutException
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


@retry(
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=0.5, max=8.0),
    retry=retry_if_exception(_is_retryable),
    before_sleep=before_sleep_log(logger, logging.WARNING),  # retries/backoff are never silent
    reraise=True,
)
def _fetch(url: str) -> httpx.Response:
    _throttle()
    response = _get_client().get(url)
    response.raise_for_status()
    return response


def _cache_path(url: str) -> Path:
    """Deterministic bronze path for `url`.

    Sanitize host+path+query into one filename; the EDGAR URL's own suffix (.json/.htm/.xml) becomes
    the extension, so offline reads and live writes agree without inspecting content-type.
    """
    parts = urlsplit(url)
    raw = parts.netloc + parts.path
    if parts.query:
        raw += "_" + parts.query
    name = _UNSAFE.sub("_", raw).strip("_")
    return BRONZE_DIR / name


def _log(url: str, *, status: str, cache_hit: bool, start: float) -> None:
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "edgar request url=%s status=%s cache_hit=%s elapsed_ms=%d",
        url,
        status,
        str(cache_hit).lower(),
        elapsed_ms,
    )


def get_bytes(url: str) -> bytes:
    """GET `url` as raw bytes, mirroring to / replaying from the bronze cache.

    from_cache=True reads the mirrored file and raises FileNotFoundError if it is missing, so an
    offline replay is exact and never silently degrades to a partial run.
    """
    path = _cache_path(url)
    start = time.monotonic()
    if from_cache:
        if not path.exists():
            raise FileNotFoundError(
                f"--from-cache: no bronze file for {url} (expected {path}); run a live ingest first"
            )
        body = path.read_bytes()
        _log(url, status="cache", cache_hit=True, start=start)
        return body

    response = _fetch(url)
    body = response.content
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a crash mid-write cannot leave a truncated file for --from-cache to read.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    _log(url, status=str(response.status_code), cache_hit=False, start=start)
    return body


def get_json(url: str) -> Any:
    """GET and parse a JSON EDGAR endpoint (company_tickers, companyfacts, submissions)."""
    return json.loads(get_bytes(url))
