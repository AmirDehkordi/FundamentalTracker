"""The agent loop (agent/loop.py): scripted fake client + seeded SQLite, network-free.

Tool calls in the scripts execute against the real seed, so only the model's *decisions* are faked;
the tool *outputs* stay honest.
"""

from __future__ import annotations

import time

from openai import OpenAIError
from sqlalchemy.orm import Session

from fixtures.fake_llm import (
    FakeOpenAI,
    custom_tool_call,
    empty_choices,
    final_response,
    malformed_tool_call,
    raw_final,
    raw_tool_call,
    refusal_final,
    stop_turn,
    tool_call,
    tool_response,
)
from tracker.agent import loop
from tracker.api.schemas import Message

_MODEL = "fake-model"
_CIT = {
    "source_type": "fundamental",
    "ticker": "AAPL",
    "fiscal_year": 2025,
    "accession": "0000320193-2025-10K",
    "detail": "Trailing P/E 25.6, FY2025 (ended 27 Sep 2025)",
}


def _run(
    session: Session, client: FakeOpenAI, question: str = "q", history: list[Message] | None = None
):
    return loop.run(question, history or [], session=session, client=client, model=_MODEL)


def test_routes_to_single_tool(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            tool_response(tool_call("c1", "get_valuation", {"ticker": "AAPL"})),
            stop_turn(),
            final_response(
                {"answer_md": "AAPL trailing P/E is 25.6 for FY2025.", "citations": [_CIT]}
            ),
        ]
    )
    answer = _run(db_session, client, "What is AAPL's P/E?")
    assert answer.declined is False
    assert [t.tool for t in answer.trace] == ["get_valuation"]
    assert answer.citations[0].ticker == "AAPL"
    assert len(client.calls) == 3


def test_two_tool_cross_modal_trace_in_order(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            tool_response(
                tool_call("c1", "get_valuation", {"ticker": "AAPL"}),
                tool_call("c2", "search_filings", {"ticker": "AAPL", "query": "supply"}),
            ),
            stop_turn(),
            final_response({"answer_md": "P/E 25.6; risks cite supply.", "citations": [_CIT]}),
        ]
    )
    answer = _run(db_session, client)
    assert [t.tool for t in answer.trace] == ["get_valuation", "search_filings"]
    assert answer.trace[0].args == {"ticker": "AAPL"}

    # Grounding lock-in: the tool outputs (and the assistant tool_calls that requested them) must
    # actually reach the model on the final turn — not just show up in the trace.
    final_msgs = client.calls[-1]["messages"]
    assistant_calls = {
        t["id"] for m in final_msgs if m["role"] == "assistant" for t in m.get("tool_calls", [])
    }
    assert assistant_calls == {"c1", "c2"}
    tool_msgs = [m for m in final_msgs if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in tool_msgs} == {"c1", "c2"}
    # a REAL seeded value (AAPL's FY2025 EPS accession) was forwarded to the model
    assert any("0000320193-2025-10K" in m["content"] for m in tool_msgs)


def test_refusal_fills_decline_reason(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            stop_turn("declining"),
            final_response(
                {
                    "answer_md": "Out of scope.",
                    "declined": True,
                    "decline_reason": "The tracker holds reported historicals only.",
                }
            ),
        ]
    )
    answer = _run(db_session, client, "What will AAPL earn next year?")
    assert answer.declined is True
    assert answer.decline_reason == "The tracker holds reported historicals only."
    assert answer.trace == []
    assert len(client.calls) == 2


def test_schema_retry_recovers(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            stop_turn(),
            final_response({"answer_md": "x", "bogus": 1}),  # extra field -> extra='forbid' fails
            final_response({"answer_md": "Revenue was $300B in FY2025.", "citations": [_CIT]}),
        ]
    )
    answer = _run(db_session, client)
    assert answer.declined is False
    assert answer.answer_md == "Revenue was $300B in FY2025."
    assert len(client.calls) == 3


def test_citation_enforcement_retry(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            stop_turn(),
            final_response({"answer_md": "Revenue was $300B.", "citations": []}),  # digits, no cite
            final_response({"answer_md": "Revenue was $300B.", "citations": [_CIT]}),
        ]
    )
    answer = _run(db_session, client)
    assert answer.citations  # the enforcement retry supplied them
    assert len(client.calls) == 3


def test_arg_validation_surfaces_as_tool_error(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            tool_response(tool_call("c1", "compare_companies", {"metric": "bogus"})),
            stop_turn(),
            final_response({"answer_md": "Could not compute.", "citations": []}),
        ]
    )
    answer = _run(db_session, client)  # must not raise
    assert [t.tool for t in answer.trace] == ["compare_companies"]
    assert "invalid_arguments" in answer.trace[0].result_summary


def test_history_and_system_prompt_seed_the_conversation(db_session: Session) -> None:
    client = FakeOpenAI([stop_turn(), final_response({"answer_md": "No figures here."})])
    _run(
        db_session,
        client,
        "and now?",
        history=[Message(role="user", content="hi"), Message(role="assistant", content="hello")],
    )
    roles = [m["role"] for m in client.calls[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_openai_error_on_tool_turn_declines(db_session: Session) -> None:
    client = FakeOpenAI([OpenAIError("boom")])
    answer = _run(db_session, client)
    assert answer.declined is True
    assert answer.decline_reason == "The analysis backend is temporarily unavailable."


def test_openai_error_on_final_turn_declines(db_session: Session) -> None:
    client = FakeOpenAI([stop_turn(), OpenAIError("boom")])
    answer = _run(db_session, client)
    assert answer.declined is True
    assert answer.decline_reason == "Internal formatting error."


def test_schema_invalid_twice_declines(db_session: Session) -> None:
    client = FakeOpenAI([stop_turn(), raw_final("not json at all"), raw_final("still not json")])
    answer = _run(db_session, client)
    assert answer.declined is True
    assert answer.decline_reason == "Internal formatting error."
    assert len(client.calls) == 3


def test_deadline_short_circuits_tool_loop(db_session: Session) -> None:
    client = FakeOpenAI([final_response({"answer_md": "No figures here."})])
    answer = loop.run(
        "q", [], session=db_session, client=client, model=_MODEL, deadline=time.monotonic() - 1
    )
    assert answer.declined is False
    assert len(client.calls) == 1  # went straight to the final turn, no tool turn


def test_malformed_tool_arguments_recover(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            tool_response(raw_tool_call("c1", "get_valuation", "{not json")),
            stop_turn(),
            final_response({"answer_md": "Could not parse the request."}),
        ]
    )
    answer = _run(db_session, client)  # must not raise
    assert answer.trace[0].args == {"_raw": "{not json"}
    assert "invalid_arguments" in answer.trace[0].result_summary


def test_turn_cap_reached_then_finalizes(db_session: Session) -> None:
    call = tool_call("c1", "list_universe", {})
    client = FakeOpenAI([tool_response(call)] * 5 + [final_response({"answer_md": "Done."})])
    answer = _run(db_session, client)
    assert len(answer.trace) == 5  # capped at _MAX_TURNS, never a 6th tool turn
    assert answer.declined is False
    assert len(client.calls) == 6  # 5 tool turns + 1 final


def test_empty_choices_on_tool_turn_declines(db_session: Session) -> None:
    client = FakeOpenAI([empty_choices()])  # provider returned no choices
    answer = _run(db_session, client)  # must not IndexError
    assert answer.declined is True
    assert answer.decline_reason == "The analysis backend returned an unexpected response."


def test_empty_choices_on_final_turn_declines(db_session: Session) -> None:
    client = FakeOpenAI([stop_turn(), empty_choices(), empty_choices()])
    answer = _run(db_session, client)  # content None -> ValidationError -> retry -> decline
    assert answer.declined is True
    assert answer.decline_reason == "Internal formatting error."


def test_unusable_tool_calls_are_dropped_not_raised(db_session: Session) -> None:
    # A spec-violating proxy sends a non-function call and a function call with a null function.
    # run() must degrade, not raise: both are skipped and the loop finalizes with what it has.
    client = FakeOpenAI(
        [
            tool_response(custom_tool_call("cust"), malformed_tool_call("bad")),
            final_response({"answer_md": "No usable tool call was made."}),
        ]
    )
    answer = _run(db_session, client)  # must not raise
    assert answer.declined is False
    assert answer.trace == []  # neither unusable call was executed or traced


def test_final_turn_refusal_becomes_decline(db_session: Session) -> None:
    client = FakeOpenAI([stop_turn(), refusal_final("I can't help with that request.")])
    answer = _run(db_session, client)
    assert answer.declined is True
    assert answer.decline_reason == "I can't help with that request."


def test_truncate_caps_summary_at_120_with_ellipsis() -> None:
    out = loop._truncate("x" * 200)
    assert len(out) == 120  # the P8 <=120 result_summary invariant
    assert out.endswith("…")
    assert loop._truncate("short") == "short"


def test_citation_retry_failure_keeps_original(db_session: Session) -> None:
    client = FakeOpenAI(
        [
            stop_turn(),
            final_response({"answer_md": "Revenue was $300B.", "citations": []}),
            OpenAIError("boom"),  # the enforcement retry's final call fails -> keep the original
        ]
    )
    answer = _run(db_session, client)
    assert answer.answer_md == "Revenue was $300B."
    assert answer.citations == []
