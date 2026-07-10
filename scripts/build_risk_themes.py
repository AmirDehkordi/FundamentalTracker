"""Precompute risk-factor themes for the tracked universe and persist to `risk_themes`.

Thin by design: get_or_build_themes (agent/riskdiff_themes.py) already does cache-check / generate /
persist — this script just calls it once per company and lets that function do the rest. Needs a
live LLM key (LLM_BASE_URL/LLM_API_KEY/LLM_MODEL). Run before `make seed-dump` so the themes ship
baked into seed/init/01_seed.sql.gz and grading never needs a live key.
"""

from __future__ import annotations

import logging

from tracker.agent import llm, riskdiff_themes
from tracker.config import get_settings
from tracker.db.session import session_scope
from tracker.services import fundamentals, riskdiff

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scripts.build_risk_themes")


def main() -> None:
    if not llm.llm_configured():
        raise SystemExit("No LLM configured (LLM_BASE_URL/LLM_API_KEY/LLM_MODEL) — nothing to do.")

    client = llm.get_client()
    model = get_settings().llm_model
    with session_scope() as session:
        for company in fundamentals.list_companies(session):
            diff = riskdiff.diff_risk_factors(session, company.cik, item="1A")
            if not diff.available:
                logger.info("%s: no year-over-year pair, skipping", company.ticker)
                continue
            try:
                riskdiff_themes.get_or_build_themes(session, client, model, diff)
            except riskdiff_themes.RiskThemesUnavailable as exc:
                logger.warning("%s: themes unavailable: %s", company.ticker, exc)
                continue
            logger.info("%s: themes cached", company.ticker)


if __name__ == "__main__":
    main()
