"""POST /api/ask — the natural-language Q&A endpoint (P8).

The agent loop is synchronous and blocking (the OpenAI client blocks), so it runs in a threadpool
under `asyncio.wait_for`: a slow LLM can never hang the request, and a timeout degrades to a
declined `FinalAnswer` (HTTP 200), never a 500. `loop.run` is itself total (never raises); the bare
`except` here is belt-and-suspenders so the endpoint's no-500 guarantee holds unconditionally.

Session ownership is deliberate: the worker opens AND closes its own `Session` (via the injected
factory) entirely on the threadpool thread. A timed-out request returns while the worker keeps
running, so a request-scoped `Depends(get_session)` would be closed on the event-loop thread while
the orphaned worker is still querying it — a cross-thread race on a real connection pool. Owning the
session on the worker thread removes that race; the orphan safely closes its own session when done.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session, sessionmaker

from tracker.agent import loop
from tracker.agent.llm import TokenUsage, get_llm_client
from tracker.api import schemas
from tracker.config import get_settings
from tracker.db.session import get_sessionmaker

router = APIRouter(tags=["ask"])
logger = logging.getLogger("tracker.agent.api")

# Hard wall-clock: the client is ALWAYS answered within this. Sized for a reasoning model (gpt-5.5):
# a cross-modal or risk-diff question routes through several tool turns, each a few-second grounded
# LLM call, so the honest worst case is ~30-40s. A thinking indicator covers the wait.
_TIMEOUT_S = 45.0
# _SOFT_BUDGET_S makes the loop stop starting new turns, but does NOT hard-bound the worker: a turn
# begun just under it can still run one bounded LLM call (llm._CALL_TIMEOUT_S), so the worker may
# outlive the response by up to that call. That is a brief, bounded resource hold — the worker owns
# and closes its own session (see module docstring), so it is never a cross-thread race or a leak.
_SOFT_BUDGET_S = 38.0
# AskRequest is frozen, so bound oversized input HERE to cap cost/latency (question chars, history
# turns, and total question+history content so many small turns can't add up unbounded).
_MAX_QUESTION_CHARS = 4000
_MAX_HISTORY_TURNS = 20
_MAX_TOTAL_CHARS = 24000


def get_session_factory() -> sessionmaker[Session]:
    """The session factory the worker calls INSIDE its thread. A FastAPI dependency so tests can
    override it (mirrors the get_session override the other routers use)."""
    return get_sessionmaker()


@router.post("/ask", response_model=schemas.FinalAnswer, summary="Grounded natural-language Q&A")
async def ask(
    req: schemas.AskRequest,
    response: Response,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    client: Any = Depends(get_llm_client),  # `Any` keeps `import openai` out of the api layer
) -> schemas.FinalAnswer:
    started = time.perf_counter()
    total_chars = len(req.question) + sum(len(m.content) for m in req.history)
    if (
        len(req.question) > _MAX_QUESTION_CHARS
        or len(req.history) > _MAX_HISTORY_TURNS
        or total_chars > _MAX_TOTAL_CHARS
    ):
        return schemas.FinalAnswer(
            answer_md="That request is too large to process. Please shorten it.",
            declined=True,
            decline_reason="request too large",
        )

    # FinalAnswer is frozen, so token usage rides in response headers, not the body. The accumulator
    # is filled on the worker thread; read it ONLY after the executor future completes (the timeout
    # path leaves the worker running, so it must not touch `usage` there — a cross-thread race).
    usage = TokenUsage()

    def _work() -> schemas.FinalAnswer:
        session = session_factory()
        try:
            return loop.run(
                req.question,
                req.history,
                session=session,
                client=client,
                model=get_settings().llm_model,
                deadline=time.monotonic() + _SOFT_BUDGET_S,
                usage=usage,
            )
        finally:
            session.close()

    event_loop = asyncio.get_running_loop()
    try:
        answer = await asyncio.wait_for(event_loop.run_in_executor(None, _work), timeout=_TIMEOUT_S)
        if usage.total > 0:  # a proxy that omits usage leaves this at 0 -> no headers
            response.headers["X-Tracker-Prompt-Tokens"] = str(usage.prompt)
            response.headers["X-Tracker-Completion-Tokens"] = str(usage.completion)
            response.headers["X-Tracker-Total-Tokens"] = str(usage.total)
    except TimeoutError:
        answer = schemas.FinalAnswer(
            answer_md="This question took too long to analyze. Please try a narrower question.",
            declined=True,
            decline_reason="timeout",
        )
    except Exception:  # loop.run shouldn't raise; the endpoint must never 500
        logger.exception("ask handler unexpected failure")
        answer = schemas.FinalAnswer(
            answer_md="Something went wrong analyzing this question.",
            declined=True,
            decline_reason="internal error",
        )
    logger.info(
        "ask latency_ms=%.1f declined=%s q=%r",
        (time.perf_counter() - started) * 1000.0,
        answer.declined,
        req.question[:200],
    )
    return answer
