"""DB-backed risk-theme cache (services/risk_theme_cache.py) — pure DB, no LLM."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from tracker.services import risk_theme_cache as cache

NVDA_CIK = 1045810
LATEST = "0001045810-2025-10K"
PRIOR = "0001045810-2024-10K"


def _theme(direction: str, rank: int, indices: list[int]) -> cache.RiskThemeData:
    return cache.RiskThemeData(
        direction=direction,
        rank=rank,
        title=f"{direction} theme {rank}",
        summary="A clustered risk theme.",
        excerpt_indices=indices,
        paragraph_count=len(indices),
    )


def test_content_hash_is_deterministic() -> None:
    a = cache.content_hash(["x", "y"], ["z"])
    b = cache.content_hash(["x", "y"], ["z"])
    assert a == b


def test_content_hash_no_delimiter_collision() -> None:
    # A naive "".join or ",".join hash would collide these two distinct excerpt lists.
    h1 = cache.content_hash(["ab", "c"], [])
    h2 = cache.content_hash(["a", "bc"], [])
    assert h1 != h2


def test_content_hash_changes_with_order() -> None:
    h1 = cache.content_hash(["a", "b"], [])
    h2 = cache.content_hash(["b", "a"], [])
    assert h1 != h2


def test_get_cached_themes_miss_when_never_saved(db_session: Session) -> None:
    result = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, "somehash")
    assert result is None


def test_save_then_get_is_a_hit(db_session: Session) -> None:
    h = cache.content_hash(["added excerpt"], ["removed excerpt"])
    added = [_theme("added", 1, [0])]
    removed = [_theme("removed", 1, [0])]
    cache.save_themes(
        db_session, NVDA_CIK, "1A", LATEST, PRIOR, h, "fake-model", date(2026, 1, 1), added, removed
    )

    result = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h)
    assert result is not None
    assert {r.direction for r in result} == {"added", "removed"}
    assert next(r for r in result if r.direction == "added").excerpt_indices == [0]


def test_get_cached_themes_miss_on_hash_mismatch(db_session: Session) -> None:
    h = cache.content_hash(["added excerpt"], ["removed excerpt"])
    cache.save_themes(
        db_session,
        NVDA_CIK,
        "1A",
        LATEST,
        PRIOR,
        h,
        "fake-model",
        date(2026, 1, 1),
        [_theme("added", 1, [0])],
        [],
    )

    stale = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, "a-different-hash")
    assert stale is None


def test_mixed_state_one_direction_empty_still_a_hit(db_session: Session) -> None:
    # "removed" legitimately produced zero themes; only "added" rows are persisted. Must still read
    # back as a hit, not be mistaken for "never computed."
    h = cache.content_hash(["added excerpt"], [])
    cache.save_themes(
        db_session,
        NVDA_CIK,
        "1A",
        LATEST,
        PRIOR,
        h,
        "fake-model",
        date(2026, 1, 1),
        [_theme("added", 1, [0])],
        [],
    )

    result = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h)
    assert result is not None
    assert len(result) == 1
    assert result[0].direction == "added"


def test_save_themes_overwrites_stale_rows(db_session: Session) -> None:
    h1 = cache.content_hash(["old excerpt"], [])
    cache.save_themes(
        db_session,
        NVDA_CIK,
        "1A",
        LATEST,
        PRIOR,
        h1,
        "fake-model",
        date(2026, 1, 1),
        [_theme("added", 1, [0])],
        [],
    )

    h2 = cache.content_hash(["new excerpt", "second excerpt"], [])
    new_added = [_theme("added", 1, [0]), _theme("added", 2, [1])]
    cache.save_themes(
        db_session, NVDA_CIK, "1A", LATEST, PRIOR, h2, "fake-model", date(2026, 1, 2), new_added, []
    )

    result = cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h2)
    assert result is not None
    assert len(result) == 2
    assert cache.get_cached_themes(db_session, NVDA_CIK, "1A", LATEST, PRIOR, h1) is None


def test_excerpt_indices_csv_round_trips_including_empty() -> None:
    assert cache._parse_indices("") == []
    assert cache._parse_indices("2,5,9") == [2, 5, 9]
    assert cache._format_indices([]) == ""
    assert cache._format_indices([2, 5, 9]) == "2,5,9"
