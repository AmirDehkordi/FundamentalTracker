"""Eval runner: POST each evals/questions.yaml case to a running /api/ask, check its expectations,
print a results table, and write evals/last_run.md. Exits non-zero if any case fails (or any brief-*
case fails, unconditionally).

Needs a live LLM key and a running API — `make db-up && make run`, then `make evals`. Not in CI.
A pure black-box HTTP client: it imports no `tracker` internals, so the same runner works against a
local server or a remote one, and against any model (set LLM_MODEL for the label).

Env: EVALS_BASE_URL (default http://localhost:8000), EVALS_MODEL_LABEL (else LLM_MODEL else
"unknown"), EVALS_ALLOWED_FAILURES (default 0; permits N non-brief failures to still exit 0 so an
honest 11/12 can be recorded — never bypasses the brief gate, never weakens an expectation).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

_QUESTIONS = Path(__file__).parent / "questions.yaml"
_LAST_RUN = Path(__file__).parent / "last_run.md"
_CLIENT_TIMEOUT = httpx.Timeout(55.0, connect=5.0)  # exceeds the server's 45s wall-clock guard
_FOOTNOTE = (
    "Tokens = prompt+completion summed across every LLM call of the request "
    "(from the X-Tracker-*-Tokens response headers); `n/a` means the provider omitted usage. "
    "Latency is client-side wall-clock. T=tools, Decl=declined/kind/followups, "
    "Cite=citation source types + items, Rgx=answer_regex; ✓ pass, ✗ fail, – not asserted."
)


@dataclass(frozen=True)
class Expected:
    tools_any_of: list[str] | None = None
    tools_all_of: list[str] | None = None
    declined: bool | None = None
    citation_source_types: list[str] | None = None
    citation_items_any_of: list[str] | None = None
    answer_regex: str | None = None
    decline_reason_contains: str | None = None
    kind: str | None = None
    suggested_followups_min: int | None = None


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    expected: Expected


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Result:
    case: Case
    tools_used: list[str]
    checks: list[Check]
    latency_s: float
    tokens: int | None
    error: str | None = None

    @property
    def overall(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    @property
    def is_brief(self) -> bool:
        return self.case.id.startswith("brief-")


def load_cases(path: Path) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for item in raw:
        exp = item.get("expected") or {}
        cases.append(
            Case(
                id=item["id"],
                question=item["question"],
                expected=Expected(
                    tools_any_of=exp.get("tools_any_of"),
                    tools_all_of=exp.get("tools_all_of"),
                    declined=exp.get("declined"),
                    citation_source_types=exp.get("citation_source_types"),
                    citation_items_any_of=exp.get("citation_items_any_of"),
                    answer_regex=exp.get("answer_regex"),
                    decline_reason_contains=exp.get("decline_reason_contains"),
                    kind=exp.get("kind"),
                    suggested_followups_min=exp.get("suggested_followups_min"),
                ),
            )
        )
    return cases


def evaluate(case: Case, body: dict[str, Any]) -> list[Check]:
    """One Check per asserted expectation; absent expectations are skipped, not counted."""
    tools = {t.get("tool") for t in (body.get("trace") or [])}
    citations = body.get("citations") or []
    srcs = {c.get("source_type") for c in citations}
    items = {c.get("item") for c in citations}
    declined = bool(body.get("declined", False))
    answer = body.get("answer_md") or ""
    reason = body.get("decline_reason") or ""
    kind = body.get("kind")
    followups = body.get("suggested_followups") or []
    e = case.expected
    checks: list[Check] = []

    if e.tools_all_of is not None:
        missing = [t for t in e.tools_all_of if t not in tools]
        checks.append(Check("tools_all_of", not missing, f"missing {missing}" if missing else "ok"))
    if e.tools_any_of is not None:
        hit = [t for t in e.tools_any_of if t in tools]
        checks.append(Check("tools_any_of", bool(hit), "ok" if hit else f"got {sorted(tools)}"))
    if e.declined is not None:
        ok = declined == e.declined
        checks.append(Check("declined", ok, "ok" if ok else f"want {e.declined} got {declined}"))
    if e.citation_source_types is not None:
        missing = [s for s in e.citation_source_types if s not in srcs]
        checks.append(
            Check(
                "citations",
                not missing,
                f"missing {missing} (got {sorted(srcs)})" if missing else "ok",
            )
        )
    if e.citation_items_any_of is not None:
        hit = [i for i in e.citation_items_any_of if i in items]
        got = sorted(str(i) for i in items if i)
        checks.append(Check("citation_items", bool(hit), "ok" if hit else f"got {got}"))
    if e.answer_regex is not None:
        ok = re.search(e.answer_regex, answer, re.IGNORECASE) is not None
        checks.append(Check("answer_regex", ok, "ok" if ok else "no match"))
    if e.decline_reason_contains is not None:
        ok = e.decline_reason_contains in reason
        checks.append(Check("decline_reason", ok, "ok" if ok else f"reason={reason!r}"))
    if e.kind is not None:
        ok = kind == e.kind
        checks.append(Check("kind", ok, "ok" if ok else f"want {e.kind} got {kind}"))
    if e.suggested_followups_min is not None:
        ok = len(followups) >= e.suggested_followups_min
        checks.append(Check("suggested_followups", ok, "ok" if ok else f"got {len(followups)}"))
    return checks


def _tokens(headers: httpx.Headers) -> int | None:
    total = headers.get("X-Tracker-Total-Tokens")
    if total is not None:
        try:
            return int(total)
        except ValueError:
            return None
    prompt, completion = (
        headers.get("X-Tracker-Prompt-Tokens"),
        headers.get("X-Tracker-Completion-Tokens"),
    )
    if prompt is not None and completion is not None:
        try:
            return int(prompt) + int(completion)
        except ValueError:
            return None
    return None


def post_case(
    client: httpx.Client, base_url: str, case: Case
) -> tuple[dict[str, Any], float, int | None]:
    started = time.perf_counter()
    resp = client.post(f"{base_url}/api/ask", json={"question": case.question, "history": []})
    latency = time.perf_counter() - started
    resp.raise_for_status()  # /api/ask is always 200; a non-200 is a real transport/proxy fault
    body: dict[str, Any] = resp.json()
    return body, latency, _tokens(resp.headers)


def _sym(checks: list[Check], names: set[str]) -> str:
    relevant = [c for c in checks if c.name in names]
    if not relevant:
        return "–"
    return "✓" if all(c.passed for c in relevant) else "✗"


def _cells(r: Result, *, with_question: bool) -> list[str]:
    tokens = "n/a" if r.tokens is None else str(r.tokens)
    lead = [r.case.id, r.case.question] if with_question else [r.case.id]
    if r.error:
        return [*lead, "-", "–", "–", "–", "–", f"{r.latency_s:.2f}", tokens, "ERR"]
    return [
        *lead,
        ",".join(t for t in r.tools_used if t) or "-",
        _sym(r.checks, {"tools_all_of", "tools_any_of"}),
        _sym(r.checks, {"declined", "decline_reason", "kind", "suggested_followups"}),
        _sym(r.checks, {"citations", "citation_items"}),
        _sym(r.checks, {"answer_regex"}),
        f"{r.latency_s:.2f}",
        tokens,
        "PASS" if r.overall else "FAIL",
    ]


def _counts(results: list[Result]) -> tuple[int, int, int]:
    passed = sum(r.overall for r in results)
    brief_passed = sum(r.overall for r in results if r.is_brief)
    brief_total = sum(r.is_brief for r in results)
    return passed, brief_passed, brief_total


def render_console(results: list[Result]) -> str:
    header = ["ID", "TOOLS", "T", "DECL", "CITE", "RGX", "LAT(s)", "TOKENS", "RESULT"]
    rows = [_cells(r, with_question=False) for r in results]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    fmt = lambda row: "  ".join(c.ljust(widths[i]) for i, c in enumerate(row))  # noqa: E731
    table = "\n".join([fmt(header), "  ".join("-" * w for w in widths), *(fmt(r) for r in rows)])
    passed, brief_passed, brief_total = _counts(results)
    legend = "\n".join(f"  {r.case.id}: {r.case.question}" for r in results)
    return (
        f"{table}\n\n{passed}/{len(results)} passed · brief {brief_passed}/{brief_total}\n\n"
        f"legend:\n{legend}\n\n{_FOOTNOTE}"
    )


def render_markdown(results: list[Result], model: str, base_url: str, timestamp: str) -> str:
    passed, brief_passed, brief_total = _counts(results)
    head = "| ID | Question | Tools | T | Decl | Cite | Rgx | Lat(s) | Tokens | Result |"
    sep = "|----|----------|-------|---|------|------|-----|--------|--------|--------|"
    body_rows = [
        "| " + " | ".join(c.replace("|", "\\|") for c in _cells(r, with_question=True)) + " |"
        for r in results
    ]
    return (
        f"# Eval run — {timestamp}\n\n"
        f"- Model: `{model}`   Base URL: `{base_url}`\n"
        f"- Result: **{passed}/{len(results)}** passed · brief **{brief_passed}/{brief_total}**\n\n"
        + "\n".join([head, sep, *body_rows])
        + f"\n\n{_FOOTNOTE}\n\n"
        "_Committed as P9 evidence. Regenerate with `make evals`; do not edit by hand._\n"
    )


def main() -> int:
    base_url = os.environ.get("EVALS_BASE_URL", "http://localhost:8000").rstrip("/")
    model = os.environ.get("EVALS_MODEL_LABEL") or os.environ.get("LLM_MODEL") or "unknown"
    allowed = int(os.environ.get("EVALS_ALLOWED_FAILURES", "0"))
    # Space requests to stay under a provider's tokens-per-minute limit (reasoning models burn
    # 6-20k tokens/question, so 14 back-to-back can 429). Default 0 keeps prior behaviour.
    delay_s = float(os.environ.get("EVALS_DELAY_S", "0"))
    cases = load_cases(_QUESTIONS)

    results: list[Result] = []
    with httpx.Client(timeout=_CLIENT_TIMEOUT) as client:
        for i, case in enumerate(cases):
            if i and delay_s:
                time.sleep(delay_s)
            try:
                body, latency, tokens = post_case(client, base_url, case)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if not results:  # first request failed — the server almost certainly isn't up
                    print(
                        f"cannot reach {base_url}/api/ask — is the API running? (make run)\n{exc}"
                    )
                    return 2
                results.append(Result(case, [], [], 0.0, None, error=f"connect error: {exc}"))
                continue
            except httpx.HTTPError as exc:
                results.append(Result(case, [], [], 0.0, None, error=str(exc)))
                continue
            tools_used = [t.get("tool") for t in (body.get("trace") or [])]
            results.append(Result(case, tools_used, evaluate(case, body), latency, tokens))

    print(render_console(results))
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    _LAST_RUN.write_text(render_markdown(results, model, base_url, timestamp), encoding="utf-8")
    print(f"\nwrote {_LAST_RUN}")

    brief_failed = any(not r.overall for r in results if r.is_brief)
    # A transport error is an infra fault, never a "known soft miss" — it must fail the run
    # regardless of EVALS_ALLOWED_FAILURES, which only masks genuine assertion misses.
    errored = any(r.error for r in results)
    nonbrief_failed = sum(r.error is None and not r.overall and not r.is_brief for r in results)
    if brief_failed or errored or nonbrief_failed > allowed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
