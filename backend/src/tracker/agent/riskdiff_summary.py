"""On-demand LLM summary of the DETERMINISTIC Item 1A diff (PLAN.md §2/§8/§14).

The diff stays deterministic (services/riskdiff.py, no LLM). This module is the only expansion of
the model's remit: given that diff's added/removed excerpts, it makes ONE grounded call for the top
added/heightened and top removed/reduced risks. Grounded structurally — the model sees only the
supplied excerpts. Schema-validated with one retry (mirrors loop._final_call); cached in-process
per (cik, fy_pair) so repeat dashboard views cost nothing. Imports openai only via agent/llm.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from tracker.agent import llm
from tracker.services.riskdiff import FilingRefData, RiskDiffResult

logger = logging.getLogger("tracker.agent.riskdiff_summary")

_MAX_ITEMS = 3  # top-N per side
_TITLE_WORDS = 8
_DETAIL_WORDS = 25
_MAX_EXCERPTS = 20  # excerpts per side sent to the model (bounds token cost)


class RiskSummaryUnavailable(Exception):
    """The summary could not be produced (LLM transport error or schema failure twice). The router
    maps this to 503 — it is NOT a data/degraded state (that is `available=False` with a note)."""


def _cap_words(value: str, limit: int) -> str:
    words = value.split()
    return value if len(words) <= limit else " ".join(words[:limit])


class _SummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str

    @field_validator("title")
    @classmethod
    def _cap_title(cls, v: str) -> str:
        return _cap_words(v, _TITLE_WORDS)

    @field_validator("detail")
    @classmethod
    def _cap_detail(cls, v: str) -> str:
        return _cap_words(v, _DETAIL_WORDS)


class _Summary(BaseModel):
    """Structured-output target for the one summarisation call."""

    model_config = ConfigDict(extra="forbid")

    added: list[_SummaryItem] = Field(default_factory=list)
    removed: list[_SummaryItem] = Field(default_factory=list)


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "risk_diff_summary",
        "schema": _Summary.model_json_schema(),
        "strict": False,  # portability; _Summary.model_validate_json is the real guard
    },
}

_SYSTEM = (
    "You summarise a DETERMINISTIC year-over-year diff of a 10-K Item 1A (risk factors) section. "
    f"Use ONLY the provided paragraphs — never outside knowledge. Return the top {_MAX_ITEMS} "
    f"ADDED or heightened risks and the top {_MAX_ITEMS} REMOVED or reduced risks. Each item: a "
    f"title of at most {_TITLE_WORDS} words and a detail of at most {_DETAIL_WORDS} words. If a "
    "side has fewer distinct risks, return fewer. Output JSON matching the schema."
)


@dataclass(frozen=True, slots=True)
class RiskSummaryItemData:
    """Mirrors schemas.RiskSummaryItem."""

    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class RiskDiffSummaryData:
    """Mirrors schemas.RiskDiffSummaryOut."""

    ticker: str
    cik: int
    item: str
    latest: FilingRefData | None
    prior: FilingRefData | None
    new_risks: list[RiskSummaryItemData]
    reduced_risks: list[RiskSummaryItemData]
    available: bool
    note: str | None


# In-process cache keyed by (cik, latest_fy, prior_fy). Small and bounded (5 companies × 1 pair);
# no eviction needed. `clear_cache` lets tests assert a cache hit makes no second LLM call.
_CACHE: dict[tuple[int, int, int], RiskDiffSummaryData] = {}


def clear_cache() -> None:
    _CACHE.clear()


def build_summary(client: Any, model: str, diff: RiskDiffResult) -> RiskDiffSummaryData:
    """Assemble the full summary payload. Degraded diffs (available=False) skip the LLM entirely."""
    if not diff.available or diff.latest is None or diff.prior is None:
        return RiskDiffSummaryData(
            ticker=diff.ticker,
            cik=diff.cik,
            item=diff.item,
            latest=diff.latest,
            prior=diff.prior,
            new_risks=[],
            reduced_risks=[],
            available=False,
            note=diff.note,
        )

    key = (diff.cik, diff.latest.fiscal_year, diff.prior.fiscal_year)
    if key in _CACHE:
        return _CACHE[key]

    summary = _summarize(client, model, diff.added, diff.removed)
    result = RiskDiffSummaryData(
        ticker=diff.ticker,
        cik=diff.cik,
        item=diff.item,
        latest=diff.latest,
        prior=diff.prior,
        new_risks=[RiskSummaryItemData(title=i.title, detail=i.detail) for i in summary.added][
            :_MAX_ITEMS
        ],
        reduced_risks=[
            RiskSummaryItemData(title=i.title, detail=i.detail) for i in summary.removed
        ][:_MAX_ITEMS],
        available=True,
        note=None,
    )
    _CACHE[key] = result
    return result


def _summarize(client: Any, model: str, added: list[str], removed: list[str]) -> _Summary:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _prompt(added, removed)},
    ]
    for attempt in (1, 2):
        try:
            resp = llm.call_final(
                client, model=model, messages=messages, response_format=_RESPONSE_FORMAT
            )
        except OpenAIError as exc:
            logger.warning("risk-diff summary call failed: %s", exc)
            raise RiskSummaryUnavailable(str(exc)) from exc
        choices = getattr(resp, "choices", None)
        content = choices[0].message.content if choices else None
        try:
            return _Summary.model_validate_json(content or "")
        except ValidationError as exc:
            if attempt == 2:
                logger.warning("risk-diff summary invalid twice: %s", exc)
                raise RiskSummaryUnavailable("summary did not match schema") from exc
            messages = messages + [
                {"role": "assistant", "content": content or ""},
                {
                    "role": "user",
                    "content": f"That did not match the schema: {exc}. Return corrected JSON only.",
                },
            ]
    raise RiskSummaryUnavailable("unreachable")  # pragma: no cover - the (1,2) loop always returns


def _prompt(added: list[str], removed: list[str]) -> str:
    def block(label: str, paras: list[str]) -> str:
        if not paras:
            return f"{label}: (none)"
        lines = "\n".join(f"- {p}" for p in paras[:_MAX_EXCERPTS])
        return f"{label}:\n{lines}"

    return (
        block("ADDED paragraphs (new or heightened risk factors)", added)
        + "\n\n"
        + block("REMOVED paragraphs (dropped or reduced risk factors)", removed)
    )
