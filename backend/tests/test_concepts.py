"""Canonical concept vocabulary (concepts.py)."""

from __future__ import annotations

from tracker import concepts


def test_canonical_is_the_frozen_nine() -> None:
    assert len(concepts.CANONICAL_CONCEPTS) == 9
    assert "revenue" in concepts.CANONICAL_CONCEPTS
    assert "sga" not in concepts.CANONICAL_CONCEPTS


def test_derivation_inputs_are_stored_but_not_canonical() -> None:
    assert concepts.DERIVATION_INPUTS == frozenset({"sga", "rnd"})
    assert concepts.ALL_STORED_CONCEPTS == concepts.CANONICAL_CONCEPTS | {"sga", "rnd"}


def test_type_guards() -> None:
    assert concepts.is_canonical_concept("revenue")
    assert not concepts.is_canonical_concept("sga")
    assert concepts.is_stored_concept("sga")
    assert not concepts.is_stored_concept("bogus")
