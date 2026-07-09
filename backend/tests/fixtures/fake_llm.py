"""A scripted, network-free stand-in for the OpenAI client (P8 agent tests).

Mimics exactly the surface loop.py touches: `client.chat.completions.create(**kwargs)` returning
objects with `choices[0].message.{content, tool_calls[i].id/.type/.function.name/.arguments}` and
`usage.prompt_tokens/.completion_tokens`. Responses are popped in order; a scripted `Exception` is
raised (to drive the OpenAI-error paths). Built from `SimpleNamespace`, not MagicMock (repo idiom).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def tool_call(call_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def raw_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """A tool call whose raw `arguments` string passes through verbatim (for bad-JSON tests)."""
    return SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def malformed_tool_call(call_id: str) -> SimpleNamespace:
    """A type=function call with a null function object — a spec-violating proxy shape."""
    return SimpleNamespace(id=call_id, type="function", function=None)


def custom_tool_call(call_id: str) -> SimpleNamespace:
    """A non-function tool call (e.g. an OpenAI custom tool) — the loop must skip it."""
    return SimpleNamespace(id=call_id, type="custom", custom=SimpleNamespace(name="x", input="{}"))


def _completion(
    *,
    content: str | None,
    tool_calls: list[SimpleNamespace] | None,
    usage: bool = True,
) -> SimpleNamespace:
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                finish_reason="tool_calls" if tool_calls else "stop",
                message=message,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22) if usage else None,
        model="fake",
        id="cmpl-fake",
    )


def tool_response(*calls: SimpleNamespace) -> SimpleNamespace:
    """A tool-calling turn: the model requests one or more tools."""
    return _completion(content=None, tool_calls=list(calls))


def stop_turn(content: str = "done", *, usage: bool = True) -> SimpleNamespace:
    """A tools turn where the model calls nothing (loop breaks to the final turn)."""
    return _completion(content=content, tool_calls=None, usage=usage)


def final_response(payload: dict[str, Any]) -> SimpleNamespace:
    """A structured final turn: JSON content matching (or violating, for retry tests) LlmAnswer."""
    return _completion(content=json.dumps(payload), tool_calls=None)


def raw_final(content: str) -> SimpleNamespace:
    """A final turn with arbitrary (possibly invalid) content string."""
    return _completion(content=content, tool_calls=None)


def empty_choices() -> SimpleNamespace:
    """A response with no choices (content-filter / some proxy error shapes)."""
    return SimpleNamespace(choices=[], usage=None, model="fake", id="cmpl-fake")


def refusal_final(text: str) -> SimpleNamespace:
    """A final turn carrying an SDK-native `message.refusal` and no content."""
    message = SimpleNamespace(role="assistant", content=None, tool_calls=None, refusal=text)
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, finish_reason="stop", message=message)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        model="fake",
        id="cmpl-fake",
    )


class FakeOpenAI:
    """Pops scripted responses from `.chat.completions.create`; records every call's kwargs."""

    def __init__(self, responses: list[SimpleNamespace | Exception]) -> None:
        self._responses: list[SimpleNamespace | Exception] = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeOpenAI ran out of scripted responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
