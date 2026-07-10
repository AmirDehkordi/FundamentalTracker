"""DB-backed cache for agent/riskdiff_themes.py's clustered risk themes.

The only services/ module that writes (agent/riskdiff_themes.py orchestrates: check the cache here,
call the LLM on a miss, persist here) — a narrow, disclosed exception to "services/ reads DB": the
alternative, raw SQL inside agent/, would scatter DB access outside services/. No HTTP out, no LLM.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tracker.db.models import RiskTheme


@dataclass(frozen=True, slots=True)
class RiskThemeData:
    """Mirrors one RiskTheme row (minus generated_at/content_hash, which are cache bookkeeping)."""

    direction: str  # "added" | "removed"
    rank: int
    title: str
    summary: str
    excerpt_indices: list[int]
    paragraph_count: int


def content_hash(added: list[str], removed: list[str]) -> str:
    """Hash of the ordered excerpt lists a theme set was generated from.

    JSON serialisation (not a naive delimiter join) so no excerpt pair can collide into the same
    hash. Detects the diff algorithm ever producing different excerpts for the same accession pair
    — the natural key (accessions) alone can't express that kind of staleness.
    """
    payload = json.dumps({"added": added, "removed": removed})
    return hashlib.sha256(payload.encode()).hexdigest()


def _parse_indices(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x]


def _format_indices(indices: list[int]) -> str:
    return ",".join(str(i) for i in indices)


def get_cached_themes(
    session: Session,
    cik: int,
    item: str,
    latest_accession: str,
    prior_accession: str,
    expected_hash: str,
) -> list[RiskThemeData] | None:
    """The cached theme rows for this filing pair, or None if never computed or stale.

    A hit may legitimately carry zero rows for one direction (that side produced no themes) — the
    caller (get_or_build_themes) only ever persists a fully-computed set, so "some rows, matching
    hash" always means "this direction was genuinely empty," never "never computed."
    """
    rows = list(
        session.scalars(
            select(RiskTheme)
            .where(
                RiskTheme.cik == cik,
                RiskTheme.item == item,
                RiskTheme.latest_accession == latest_accession,
                RiskTheme.prior_accession == prior_accession,
            )
            .order_by(RiskTheme.direction, RiskTheme.rank)
        ).all()
    )
    if not rows:
        return None
    if any(row.content_hash != expected_hash for row in rows):
        return None
    return [
        RiskThemeData(
            direction=row.direction,
            rank=row.rank,
            title=row.title,
            summary=row.summary,
            excerpt_indices=_parse_indices(row.excerpt_indices),
            paragraph_count=row.paragraph_count,
        )
        for row in rows
    ]


def save_themes(
    session: Session,
    cik: int,
    item: str,
    latest_accession: str,
    prior_accession: str,
    content_hash_: str,
    model: str,
    generated_at: date,
    added: list[RiskThemeData],
    removed: list[RiskThemeData],
) -> None:
    """Replace any cached rows for this filing pair with a freshly-generated set.

    Only ever called after a full successful generation (agent/riskdiff_themes.py), so a failed
    regeneration attempt never clobbers a previously-good cache — the delete only happens here, on
    the success path.
    """
    session.execute(
        delete(RiskTheme).where(
            RiskTheme.cik == cik,
            RiskTheme.item == item,
            RiskTheme.latest_accession == latest_accession,
            RiskTheme.prior_accession == prior_accession,
        )
    )
    for theme in (*added, *removed):
        session.add(
            RiskTheme(
                cik=cik,
                item=item,
                latest_accession=latest_accession,
                prior_accession=prior_accession,
                direction=theme.direction,
                rank=theme.rank,
                title=theme.title,
                summary=theme.summary,
                excerpt_indices=_format_indices(theme.excerpt_indices),
                paragraph_count=theme.paragraph_count,
                model=model,
                generated_at=generated_at,
                content_hash=content_hash_,
            )
        )
    session.commit()
