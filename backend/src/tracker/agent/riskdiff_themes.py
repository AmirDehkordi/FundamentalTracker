"""LLM theme-clustering of the DETERMINISTIC Item 1A diff into the top 3 added / top 3 removed
risk THEMES.

The diff stays deterministic (services/riskdiff.py, no LLM). This module runs a sequential 3-stage
pipeline — draft candidate themes, critique/ground them, finalize the top few — so nothing gets
silently dropped: stage 2 always runs (not conditional) and is fed a Python-computed coverage report
(which excerpts no candidate theme cites) alongside a quality critique instruction. Final grounding
(every citation index in range) is enforced in Python, not just prompted. Results persist to the
`risk_themes` table (services/risk_theme_cache.py) keyed by the filing pair + a content hash, so a
cache hit costs zero LLM calls and works even with no LLM configured — the whole point of baking
results into the committed seed. Imports openai only via agent/llm.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from tracker.agent import llm
from tracker.services import risk_theme_cache as cache
from tracker.services.riskdiff import FilingRefData, RiskDiffResult

logger = logging.getLogger("tracker.agent.riskdiff_themes")

_MAX_THEMES = 3  # top-N themes per side, after ranking/merging
_TITLE_WORDS = 6
_SUMMARY_WORDS = 30
_MAX_EXCERPTS = 60  # excerpts per side sent to the model; real diffs run ~30-40 (riskdiff.py)
_THEME_CALL_TIMEOUT_S = 90.0  # each stage clusters/critiques up to 120 excerpts; see _generate


class RiskThemesUnavailable(Exception):
    """The theme summary could not be produced: LLM transport error, schema failure twice, or a
    side with real excerpts where every candidate theme failed grounding. The router maps this to
    503 — it is NOT a data/degraded state (that is `available=False` with a note)."""


# --- structured-output schema (shared by all 3 pipeline stages) --------------------------------


def _cap_words(value: str, limit: int) -> str:
    words = value.split()
    return value if len(words) <= limit else " ".join(words[:limit])


class _Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    excerpt_indices: list[int] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _cap_title(cls, v: str) -> str:
        return _cap_words(v, _TITLE_WORDS)

    @field_validator("summary")
    @classmethod
    def _cap_summary(cls, v: str) -> str:
        return _cap_words(v, _SUMMARY_WORDS)


class _ThemeSet(BaseModel):
    """Structured-output target for every stage: draft, critique, and finalize all return this
    same shape, just with different cardinality expectations set by the prompt."""

    model_config = ConfigDict(extra="forbid")

    added: list[_Theme] = Field(default_factory=list)
    removed: list[_Theme] = Field(default_factory=list)


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "risk_diff_themes",
        "schema": _ThemeSet.model_json_schema(),
        "strict": False,  # portability; _ThemeSet.model_validate_json is the real guard
    },
}


# --- data shapes returned to callers ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskThemeItemData:
    """Mirrors schemas.RiskThemeItem."""

    title: str
    summary: str
    paragraph_count: int


@dataclass(frozen=True, slots=True)
class RiskDiffThemesData:
    """Mirrors schemas.RiskDiffThemesOut."""

    ticker: str
    cik: int
    item: str
    latest: FilingRefData | None
    prior: FilingRefData | None
    added_themes: list[RiskThemeItemData]
    removed_themes: list[RiskThemeItemData]
    available: bool
    note: str | None


# --- orchestration -------------------------------------------------------------------------------


def get_or_build_themes(
    session: Session,
    client: Any | None,
    model: str,
    diff: RiskDiffResult,
    *,
    as_of: date | None = None,
) -> RiskDiffThemesData:
    """Cache-first: a hit costs zero LLM calls and works with `client=None`. A miss with no client
    configured raises — there is nothing to serve."""
    if not diff.available or diff.latest is None or diff.prior is None:
        return _empty_result(diff, available=False, note=diff.note)

    if not diff.added and not diff.removed:
        # Two FYs exist but nothing changed after denoise. Skip the cache/LLM entirely — there is
        # nothing to theme, and nothing to persist (an empty write here would be indistinguishable
        # from "never computed" on the next read, forcing a live call forever for this company).
        return _empty_result(diff, available=True, note=None)

    truncation_note = _truncation_note(diff.added, diff.removed)

    content_hash = cache.content_hash(diff.added, diff.removed)
    cached = cache.get_cached_themes(
        session, diff.cik, diff.item, diff.latest.accession, diff.prior.accession, content_hash
    )
    if cached is not None:
        return _to_data(diff, cached, note=truncation_note)

    if client is None:
        raise RiskThemesUnavailable("no cached themes and no LLM configured")

    added_themes, removed_themes = _generate(client, model, diff.added, diff.removed)
    cache.save_themes(
        session,
        diff.cik,
        diff.item,
        diff.latest.accession,
        diff.prior.accession,
        content_hash,
        model,
        as_of or date.today(),
        added_themes,
        removed_themes,
    )
    return _to_data(diff, [*added_themes, *removed_themes], note=truncation_note)


def _truncation_note(added: list[str], removed: list[str]) -> str | None:
    if len(added) <= _MAX_EXCERPTS and len(removed) <= _MAX_EXCERPTS:
        return None
    return f"Only the first {_MAX_EXCERPTS} excerpts per side were considered for theming."


def _to_data(
    diff: RiskDiffResult, rows: list[cache.RiskThemeData], *, note: str | None
) -> RiskDiffThemesData:
    added = sorted((r for r in rows if r.direction == "added"), key=lambda r: r.rank)
    removed = sorted((r for r in rows if r.direction == "removed"), key=lambda r: r.rank)
    return RiskDiffThemesData(
        ticker=diff.ticker,
        cik=diff.cik,
        item=diff.item,
        latest=diff.latest,
        prior=diff.prior,
        added_themes=[_to_item(r) for r in added],
        removed_themes=[_to_item(r) for r in removed],
        available=True,
        note=note,
    )


def _to_item(row: cache.RiskThemeData) -> RiskThemeItemData:
    return RiskThemeItemData(
        title=row.title, summary=row.summary, paragraph_count=row.paragraph_count
    )


def _empty_result(diff: RiskDiffResult, *, available: bool, note: str | None) -> RiskDiffThemesData:
    return RiskDiffThemesData(
        ticker=diff.ticker,
        cik=diff.cik,
        item=diff.item,
        latest=diff.latest,
        prior=diff.prior,
        added_themes=[],
        removed_themes=[],
        available=available,
        note=note,
    )


# --- the 3-stage pipeline ------------------------------------------------------------------------


def _generate(
    client: Any, model: str, added: list[str], removed: list[str]
) -> tuple[list[cache.RiskThemeData], list[cache.RiskThemeData]]:
    added_n = min(len(added), _MAX_EXCERPTS)
    removed_n = min(len(removed), _MAX_EXCERPTS)

    # llm.py's client-wide 20s timeout is sized for the single-call /ask path; clustering ~60
    # excerpts with full-coverage citations genuinely runs long (~40s observed on a real diff).
    # with_options() overrides the timeout for just these calls without touching the shared client
    # (llm.py stays the only place one is constructed from settings) or that endpoint's UX budget.
    client = client.with_options(timeout=_THEME_CALL_TIMEOUT_S)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _draft_prompt(added, removed)},
    ]
    draft = _structured_call(client, model, messages, "draft")
    messages = messages + [{"role": "assistant", "content": draft.model_dump_json()}]

    report = _coverage_report(draft, added_n, removed_n)
    messages = messages + [{"role": "user", "content": _critique_prompt(report)}]
    critiqued = _structured_call(client, model, messages, "critique")
    messages = messages + [{"role": "assistant", "content": critiqued.model_dump_json()}]

    messages = messages + [{"role": "user", "content": _finalize_prompt()}]
    final = _structured_call(client, model, messages, "finalize")

    return _ground_and_rank(final, added_n, removed_n)


def _structured_call(
    client: Any, model: str, messages: list[dict[str, Any]], phase: str
) -> _ThemeSet:
    """One structured call for `phase`; on schema failure retry ONCE with the error appended, else
    raise. Retries are local to this call — the caller's carried-forward conversation only ever sees
    the final valid output, never the failed intermediate attempts (mirrors loop._final_call)."""
    local = messages
    for attempt in (1, 2):
        try:
            resp = llm.call_final(
                client, model=model, messages=local, response_format=_RESPONSE_FORMAT
            )
        except OpenAIError as exc:
            logger.warning("risk-theme %s call failed: %s", phase, exc)
            raise RiskThemesUnavailable(str(exc)) from exc
        choices = getattr(resp, "choices", None)
        content = choices[0].message.content if choices else None
        try:
            return _ThemeSet.model_validate_json(content or "")
        except ValidationError as exc:
            if attempt == 2:
                logger.warning("risk-theme %s invalid twice: %s", phase, exc)
                raise RiskThemesUnavailable(f"{phase} did not match schema") from exc
            local = local + [
                {"role": "assistant", "content": content or ""},
                {
                    "role": "user",
                    "content": f"That did not match the schema: {exc}. Return corrected JSON only.",
                },
            ]
    raise RiskThemesUnavailable("unreachable")  # pragma: no cover - the (1,2) loop always returns


def _ground_and_rank(
    final: _ThemeSet, added_n: int, removed_n: int
) -> tuple[list[cache.RiskThemeData], list[cache.RiskThemeData]]:
    added_out = _ground_side("added", final.added, added_n)
    removed_out = _ground_side("removed", final.removed, removed_n)
    # A side that HAD excerpts but ended with zero valid themes is real content loss, not a quiet
    # side — surface it as unavailable rather than caching a falsely-empty result. A side with zero
    # source excerpts to begin with legitimately has zero themes (handled by get_or_build_themes's
    # both-sides-empty short-circuit when BOTH sides are like that).
    if added_n and not added_out:
        raise RiskThemesUnavailable("added excerpts existed but no theme survived grounding")
    if removed_n and not removed_out:
        raise RiskThemesUnavailable("removed excerpts existed but no theme survived grounding")
    return added_out, removed_out


def _ground_side(direction: str, themes: list[_Theme], n: int) -> list[cache.RiskThemeData]:
    valid: list[_Theme] = []
    for theme in themes:
        indices = theme.excerpt_indices
        if not indices or any(i < 0 or i >= n for i in indices):
            logger.warning("dropped ungrounded %s theme %r", direction, theme.title)
            continue
        valid.append(theme)
    ranked = valid[:_MAX_THEMES]
    return [
        cache.RiskThemeData(
            direction=direction,
            rank=i + 1,
            title=theme.title,
            summary=theme.summary,
            excerpt_indices=theme.excerpt_indices,
            paragraph_count=len(theme.excerpt_indices),
        )
        for i, theme in enumerate(ranked)
    ]


def _coverage_report(draft: _ThemeSet, added_n: int, removed_n: int) -> str | None:
    def _side_report(themes: list[_Theme], n: int, label: str) -> list[str]:
        covered: set[int] = set()
        invalid: list[int] = []
        for theme in themes:
            for i in theme.excerpt_indices:
                if 0 <= i < n:
                    covered.add(i)
                else:
                    invalid.append(i)
        uncovered = sorted(set(range(n)) - covered)
        lines = []
        if invalid:
            lines.append(f"{label}: out-of-range indices {invalid}")
        if uncovered:
            lines.append(f"{label}: excerpts not covered by any theme: indices {uncovered}")
        return lines

    lines = _side_report(draft.added, added_n, "ADDED") + _side_report(
        draft.removed, removed_n, "REMOVED"
    )
    return "\n".join(lines) if lines else None


# --- prompts ---------------------------------------------------------------------------------


_SYSTEM = (
    "You cluster a DETERMINISTIC year-over-year diff of a 10-K Item 1A (risk factors) section into "
    "thematic groups. Use ONLY the provided paragraphs — never outside knowledge. You work through "
    "this in stages: draft candidate themes, critique/refine them, then finalize the top themes. "
    "Every theme cites the 0-based indices of the excerpts (from the correct ADDED or REMOVED "
    "list) it groups, and its summary must be supported only by those cited excerpts."
)


def _indexed_block(label: str, excerpts: list[str]) -> str:
    if not excerpts:
        return f"{label}: (none)"
    shown = excerpts[:_MAX_EXCERPTS]
    lines = "\n".join(f"{i}: {p}" for i, p in enumerate(shown))
    return f"{label}, indexed from 0:\n{lines}"


def _draft_prompt(added: list[str], removed: list[str]) -> str:
    return (
        _indexed_block("ADDED paragraphs (new or heightened risk factors)", added)
        + "\n\n"
        + _indexed_block("REMOVED paragraphs (dropped or reduced risk factors)", removed)
        + "\n\nGroup every ADDED excerpt into thematic clusters, and every REMOVED excerpt into "
        "separate thematic clusters. Return as many distinct, meaningful themes per side as the "
        "material supports — do not force excerpts on different topics into one theme, and do not "
        "invent a theme with no supporting excerpt. Every excerpt index must be cited by at least "
        f"one theme. Each theme: a title (<= {_TITLE_WORDS} words), a summary (<= {_SUMMARY_WORDS} "
        "words) grounded only in its cited excerpts, and excerpt_indices. Output JSON matching the "
        "schema."
    )


def _critique_prompt(coverage_report: str | None) -> str:
    fix = (
        f"Fix these problems first: {coverage_report}\n"
        if coverage_report
        else "No indexing problems were detected. "
    )
    return (
        f"{fix}Now critically re-examine your own draft: merge themes that are really the same "
        "underlying risk, split any theme that bundles unrelated risks, and re-check that every "
        "cited excerpt actually supports that theme's summary — drop a citation that doesn't fit, "
        "or correct the summary. Every excerpt must remain covered by some theme. Return the "
        "corrected, complete JSON."
    )


def _finalize_prompt() -> str:
    return (
        f"Finalize: return at most {_MAX_THEMES} ADDED themes and at most {_MAX_THEMES} REMOVED "
        "themes — the most material and distinct ones (merge near-duplicates if your critique left "
        f"more than {_MAX_THEMES}). If a side has fewer than {_MAX_THEMES} truly distinct themes, "
        f"return fewer — never invent one to reach {_MAX_THEMES}. Keep titles <= {_TITLE_WORDS} "
        f"words and summaries <= {_SUMMARY_WORDS} words, and keep excerpt_indices accurate for any "
        "merged theme (the union of the merged themes' indices). Output the final JSON."
    )
