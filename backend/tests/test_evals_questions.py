"""CI-safe structural validation of evals/questions.yaml (no network, no LLM, no DB).

The live eval runner (evals/run.py) needs a key and a running API, so it is not in CI; this test is
the CI-safe guard that the question set stays well-formed and its tool / source-type vocabulary does
not drift from the code (derived from the source of truth, not hard-coded)."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest
import yaml

from tracker.agent.tools import TOOLS
from tracker.api.schemas import CitationSource

_QUESTIONS = Path(__file__).parents[2] / "evals" / "questions.yaml"
_KNOWN_TOOLS = set(TOOLS)
_KNOWN_SOURCES = set(typing.get_args(CitationSource))
_EXPECT_KEYS = {
    "tools_any_of",
    "tools_all_of",
    "declined",
    "citation_source_types",
    "answer_regex",
    "decline_reason_contains",
}


def _cases() -> list[dict[str, object]]:
    return yaml.safe_load(_QUESTIONS.read_text(encoding="utf-8"))


def test_questions_file_is_a_nonempty_list() -> None:
    cases = _cases()
    assert isinstance(cases, list) and len(cases) >= 12  # brief 6 + at least 6 more


def test_ids_and_questions_are_unique() -> None:
    cases = _cases()
    ids = [c["id"] for c in cases]
    questions = [c["question"] for c in cases]
    assert len(set(ids)) == len(ids)  # no duplicate ids
    assert len(set(questions)) == len(questions)  # no accidental duplicate question (e.g. 2 vs 7)


def test_the_six_brief_cases_are_present() -> None:
    ids = [str(c["id"]) for c in _cases()]
    brief = [i for i in ids if i.startswith("brief-")]
    assert len(brief) == 6  # the brief's six questions are all present and all must pass
    assert {i.split("-")[1] for i in brief} == {str(n) for n in range(1, 7)}


@pytest.mark.parametrize("case", _cases(), ids=lambda c: str(c["id"]))
def test_case_is_well_formed(case: dict[str, object]) -> None:
    assert isinstance(case["id"], str) and case["id"].strip()
    assert isinstance(case["question"], str) and case["question"].strip()

    expected = case["expected"]
    assert isinstance(expected, dict) and expected  # non-empty
    assert set(expected) <= _EXPECT_KEYS  # no unknown expectation keys

    for key in ("tools_any_of", "tools_all_of"):
        if key in expected:
            names = expected[key]
            assert isinstance(names, list) and names
            assert set(names) <= _KNOWN_TOOLS, f"unknown tool in {key}: {set(names) - _KNOWN_TOOLS}"

    if "citation_source_types" in expected:
        srcs = expected["citation_source_types"]
        assert isinstance(srcs, list) and srcs
        assert set(srcs) <= _KNOWN_SOURCES, f"unknown source: {set(srcs) - _KNOWN_SOURCES}"

    if "declined" in expected:
        assert isinstance(expected["declined"], bool)

    if "answer_regex" in expected:
        assert isinstance(expected["answer_regex"], str)
        re.compile(expected["answer_regex"])  # raises if malformed

    if "decline_reason_contains" in expected:
        assert isinstance(expected["decline_reason_contains"], str)
        assert expected["decline_reason_contains"].strip()
