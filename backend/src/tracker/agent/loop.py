"""The agent loop: route across tools, then answer in a validated structured shape (P8).

`run()` NEVER raises — every failure (OpenAI error, bad tool JSON, handler bug, schema-invalid final
output, turn-cap, deadline) degrades to a `FinalAnswer`, most as `declined=true`. The endpoint layer
adds only the wall-clock timeout on top.

Transport ladder: tool-calling turns use function tools; the final turn binds `response_format`
json_schema to `LlmAnswer` (a trace-free variant of the frozen `FinalAnswer` — the code owns the
trace). `strict` is off for proxy/Groq portability; the real guard is
`LlmAnswer.model_validate_json` here, whose `extra="forbid"` catches hallucinated fields and drives
the one schema retry.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from tracker.agent import llm, tools
from tracker.agent.prompts import SYSTEM_PROMPT
from tracker.api.schemas import Citation, FinalAnswer, Message, ToolTrace

logger = logging.getLogger("tracker.agent.loop")

_MAX_TURNS = 5
_SUMMARY_MAX = 120


class LlmAnswer(BaseModel):
    """Structured-output target: `FinalAnswer` minus `trace` (the loop owns the trace)."""

    model_config = ConfigDict(extra="forbid")

    answer_md: str
    citations: list[Citation] = Field(default_factory=list)
    declined: bool = False
    decline_reason: str | None = None


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "final_answer",
        "schema": LlmAnswer.model_json_schema(),
        "strict": False,  # portability; LlmAnswer.model_validate_json is the real guard
    },
}


def run(
    question: str,
    history: list[Message],
    *,
    session: Session,
    client: OpenAI,
    model: str,
    deadline: float | None = None,
) -> FinalAnswer:
    """Drive tool turns then a final structured turn. Returns a `FinalAnswer`; never raises."""
    messages = _initial_messages(question, history)
    trace: list[ToolTrace] = []

    for _turn in range(_MAX_TURNS):
        if deadline is not None and time.monotonic() >= deadline:
            break  # soft deadline: stop routing and answer with what we have
        try:
            resp = llm.call_tools(
                client, model=model, messages=messages, tools=tools.openai_tools_schema()
            )
        except OpenAIError as exc:
            logger.warning("tool turn failed: %s", exc)
            return _declined("The analysis backend is temporarily unavailable.", trace)

        msg = _message(resp)  # a content-filter/proxy error can return empty choices
        if msg is None:
            return _declined("The analysis backend returned an unexpected response.", trace)
        calls = _function_calls(msg)
        if not calls:
            break  # model has stopped calling tools — ready to answer

        messages.append(
            {
                "role": "assistant",
                # "" not None: some OpenAI-compatible proxies reject a null content on tool turns.
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in calls
                ],
            }
        )
        for tc in calls:
            result = tools.call_tool(session, tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
            trace.append(
                ToolTrace(
                    tool=tc.function.name,
                    args=_safe_args(tc.function.arguments),
                    result_summary=_truncate(tools.summarize(tc.function.name, result)),
                )
            )

    return _finalize(client, model, messages, trace, deadline)


def _finalize(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    trace: list[ToolTrace],
    deadline: float | None,
) -> FinalAnswer:
    ask = messages + [
        {
            "role": "user",
            "content": "Now write the final answer as JSON matching the schema. Cite every figure.",
        }
    ]
    answer = _final_call(client, model, ask, deadline)
    if answer is None:
        return _declined("Internal formatting error.", trace)

    # Citation grounding is enforced only heuristically (a digit in answer_md with no citation); we
    # don't cross-check that a cited accession actually came back from a tool. Adequate for a
    # prototype, but a fabricated figure in free text can slip through. Retry once, then accept.
    stated_uncited = not answer.citations and any(c.isdigit() for c in answer.answer_md)
    if not answer.declined and stated_uncited and not _past(deadline):
        retry = ask + [
            {
                "role": "user",
                "content": "Your answer states figures but cites nothing. Return the same answer "
                "with a citation for every figure.",
            }
        ]
        corrected = _final_call(client, model, retry, deadline)
        if corrected is not None:
            answer = corrected  # accept best effort; the rule is retry-once, not force-decline

    return FinalAnswer(
        answer_md=answer.answer_md,
        citations=answer.citations,
        trace=trace,
        declined=answer.declined,
        decline_reason=answer.decline_reason,
    )


def _final_call(
    client: OpenAI, model: str, messages: list[dict[str, Any]], deadline: float | None
) -> LlmAnswer | None:
    """One structured call; on schema failure retry ONCE with the error appended, else None."""
    for attempt in (1, 2):
        try:
            resp = llm.call_final(
                client, model=model, messages=messages, response_format=_RESPONSE_FORMAT
            )
        except OpenAIError as exc:
            logger.warning("final call failed: %s", exc)
            return None
        msg = _message(resp)  # empty choices -> content None -> falls into the retry/decline path
        content = msg.content if msg is not None else None
        # An SDK-native refusal (message.refusal, no content) is a decline, not a format error.
        refusal = getattr(msg, "refusal", None) if msg is not None else None
        if refusal and not content:
            return LlmAnswer(answer_md=refusal, declined=True, decline_reason=refusal)
        try:
            return LlmAnswer.model_validate_json(content or "")
        except ValidationError as exc:
            if attempt == 2 or _past(deadline):  # don't burn the retry past the wall-clock budget
                logger.warning("final output invalid: %s", exc)
                return None
            messages = messages + [
                {"role": "assistant", "content": content or ""},
                {
                    "role": "user",
                    "content": f"That did not match the schema: {exc}. Return corrected JSON only.",
                },
            ]
    return None  # pragma: no cover - the (1, 2) loop always returns; kept for mypy's return check


def _initial_messages(question: str, history: list[Message]) -> list[dict[str, Any]]:
    # Message.role is only user|assistant; the system turn is constructed here, never from a client.
    msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs += [{"role": m.role, "content": m.content} for m in history]
    msgs.append({"role": "user", "content": question})
    return msgs


def _message(resp: Any) -> Any:
    """The assistant message, or None if the provider returned empty `choices` (content filter /
    some proxy error shapes) — keeps the loop from IndexError-ing out of its no-raise contract."""
    choices = getattr(resp, "choices", None)
    return choices[0].message if choices else None


def _past(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _function_calls(msg: Any) -> list[Any]:
    """Function tool calls on an assistant message. Skips non-function calls AND malformed ones
    (no `function` object or no string `name`) so a spec-violating proxy response degrades to a
    finalize-with-what-we-have instead of raising out of run()'s no-raise contract."""
    out: list[Any] = []
    for tc in msg.tool_calls or []:
        if getattr(tc, "type", None) != "function":
            continue
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None)
        if fn is None or not isinstance(name, str) or not name:
            continue
        out.append(tc)
    return out


def _safe_args(raw: str) -> dict[str, Any]:
    """Re-parse a tool-call arguments string into a dict for the trace; never raises."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


def _truncate(s: str) -> str:
    return s if len(s) <= _SUMMARY_MAX else s[: _SUMMARY_MAX - 1] + "…"


def _declined(reason: str, trace: list[ToolTrace]) -> FinalAnswer:
    return FinalAnswer(answer_md=reason, declined=True, decline_reason=reason, trace=trace)
