"""LLM transport — the ONLY place the OpenAI client is constructed (P8).

Chat Completions only, never the Responses API: the deployment targets an OpenAI-compatible proxy /
Groq, where `/v1/chat/completions` (plus function tools and `response_format`) is the portable
surface and `json_schema` *strict* mode is not guaranteed. The real structured-output guard is
`LlmAnswer.model_validate_json()` in loop.py, never the provider's schema enforcement.

Two thin helpers wrap `chat.completions.create`: one for the tool-calling turns, one for the final
structured turn. Both log model, latency, and token usage per call.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletion

from tracker.config import get_settings

logger = logging.getLogger("tracker.agent.llm")

# Bound a single call so a hung provider can't outlive the endpoint's wall-clock guard by minutes
# (the SDK default is ~600s). max_retries=0: loop.py owns retry policy itself (deadline-aware, and
# only for transient error types) rather than a blind SDK-level retry.
_CALL_TIMEOUT_S = 20.0


@dataclass
class TokenUsage:
    """Accumulates prompt/completion tokens across the several LLM calls of one request. Passed down
    the loop; the endpoint surfaces the totals as response headers (the frozen FinalAnswer body
    can't carry them). A provider that omits `usage` leaves the counters at 0 -> no headers."""

    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    def add(self, resp: ChatCompletion) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.prompt += usage.prompt_tokens or 0
        self.completion += usage.completion_tokens or 0


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Process-wide client. The httpx-backed client is thread-safe and pools connections, so the
    threadpool-executed loop can share one instance across requests. Reads settings once."""
    s = get_settings()
    return OpenAI(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key.get_secret_value(),
        timeout=_CALL_TIMEOUT_S,
        max_retries=0,
    )


def get_llm_client() -> OpenAI:
    """FastAPI dependency seam for POST /api/ask. Tests override this with a scripted fake client,
    which keeps `import openai` physically confined to the agent package."""
    return get_client()


def llm_configured() -> bool:
    """True iff a non-blank LLM API key is set. The LLM-optional endpoints (risk-diff summary) 503
    on False instead of constructing a client that would raise. Never raises."""
    try:
        return bool(get_settings().llm_api_key.get_secret_value().strip())
    except Exception:  # settings fail to load (key absent entirely) -> not configured
        logger.debug(
            "llm_configured: settings unavailable, treating as not configured", exc_info=True
        )
        return False


def _timed_create(client: OpenAI, *, phase: str, **kwargs: Any) -> ChatCompletion:
    start = time.perf_counter()
    # non-streaming call; annotate so the **kwargs overload doesn't widen the return to Any
    resp: ChatCompletion = client.chat.completions.create(**kwargs)
    latency_ms = (time.perf_counter() - start) * 1000.0
    usage = resp.usage  # proxies may omit usage entirely
    logger.info(
        "llm_call phase=%s model=%s latency_ms=%.1f prompt_tokens=%s completion_tokens=%s "
        "finish=%s",
        phase,
        kwargs.get("model"),
        latency_ms,
        usage.prompt_tokens if usage is not None else None,
        usage.completion_tokens if usage is not None else None,
        resp.choices[0].finish_reason if resp.choices else None,
    )
    return resp


def call_tools(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    usage: TokenUsage | None = None,
) -> ChatCompletion:
    """One tool-calling turn. `tool_choice="auto"` lets the model stop calling tools when ready."""
    resp = _timed_create(
        client, phase="tools", model=model, messages=messages, tools=tools, tool_choice="auto"
    )
    if usage is not None:
        usage.add(resp)
    return resp


def call_final(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any],
    usage: TokenUsage | None = None,
) -> ChatCompletion:
    """The final structured turn: no tools. Temperature is left at the provider default — reasoning
    models (e.g. gpt-5.5) reject any non-default value; JSON stability comes from `response_format`
    plus the `LlmAnswer` validation guard in loop.py, not a low temperature."""
    resp = _timed_create(
        client,
        phase="final",
        model=model,
        messages=messages,
        response_format=response_format,
    )
    if usage is not None:
        usage.add(resp)
    return resp
