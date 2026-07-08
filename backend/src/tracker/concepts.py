"""Canonical financial concepts, defined once (PLAN.md §3).

The 9-member `Concept` Literal is the frozen, user-facing metric vocabulary. `sga`/`rnd` are
ingested and stored as fundamentals rows purely to DERIVE `operating_income` for filers like ETN
that stopped tagging `OperatingIncomeLoss` after FY2019 (sec-edgar skill); they never surface as
metrics, so they stay OUT of the canonical Literal. The DB `concept` column is free `text`, so there
is no enum constraint to fight — these types are for validation/typing only.
"""

from __future__ import annotations

from typing import Literal, TypeGuard, get_args

# Order matches PLAN.md §3. FROZEN: response models type metrics against this vocabulary.
Concept = Literal[
    "revenue",
    "net_income",
    "eps_diluted",
    "gross_profit",
    "cost_of_revenue",
    "operating_income",
    "cfo",
    "capex",
    "shares_diluted",
]

# Derivation inputs — stored, but never shown as a metric.
DerivationInput = Literal["sga", "rnd"]

# Everything legally allowed in fundamentals.concept.
StoredConcept = Concept | DerivationInput

# Runtime validation sets — derived from the Literals so there is ONE source of truth.
CANONICAL_CONCEPTS: frozenset[str] = frozenset(get_args(Concept))
DERIVATION_INPUTS: frozenset[str] = frozenset(get_args(DerivationInput))
ALL_STORED_CONCEPTS: frozenset[str] = CANONICAL_CONCEPTS | DERIVATION_INPUTS


def is_canonical_concept(value: str) -> TypeGuard[Concept]:
    """True iff `value` is one of the 9 user-facing metrics."""
    return value in CANONICAL_CONCEPTS


def is_stored_concept(value: str) -> TypeGuard[StoredConcept]:
    """True iff `value` may be persisted in fundamentals.concept (metrics + derivation inputs)."""
    return value in ALL_STORED_CONCEPTS
