"""Richer deterministic fixture for the metrics/valuation/compare services.

`mini_seed` only carries revenue/net_income/eps_diluted and no negatives, so it can't exercise the
metric guards. This seed adds two companies on a shared SQLite engine (see the `rich_session`
fixture) and does NOT touch mini_seed (whose exact counts other tests assert):

  FULLCO (cik 1000001) — all 9 concepts, FY2021–2025, positive and growing; tuned so FY2025 gives a
    hand-checkable P/E: close 179 / eps 7 = 25.5714…, and P/S 179 * 16e9 / 400e9 = 7.16.
  EDGECO (cik 1000002) — every None-with-reason guard: eps ≤ 0 (P/E n.m.), net_income ≤ 0
    (fcf_conversion undefined), an operating-income sign flip (operating leverage n.m.), a
    non-positive YoY base, a skipped FY (YoY gap), a restated revenue (superseded_*), and no
    shares_diluted (P/S None).

All magnitudes are round base-10 so SQLite's NUMERIC↔float round-trip stays exact.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from tracker.db.models import Company, Fundamental, Price

FULLCO_CIK = 1000001
EDGECO_CIK = 1000002

_UNITS = {
    "revenue": "USD",
    "cost_of_revenue": "USD",
    "gross_profit": "USD",
    "operating_income": "USD",
    "net_income": "USD",
    "cfo": "USD",
    "capex": "USD",
    "eps_diluted": "USD/shares",
    "shares_diluted": "shares",
}

# EDGECO: explicit per-FY values (2024 skipped -> a YoY gap). eps ≤ 0 every year, so the latest
# reported FY (2025) drives P/E n.m.; the 2022->2023 operating-income sign flip and ≤0 YoY base
# fall out of these numbers.
_EDGECO_FACTS: dict[int, dict[str, Decimal]] = {
    2022: {
        "revenue": Decimal("100000000000"),
        "cost_of_revenue": Decimal("80000000000"),
        "gross_profit": Decimal("20000000000"),
        "operating_income": Decimal("-5000000000"),
        "net_income": Decimal("-10000000000"),
        "cfo": Decimal("5000000000"),
        "capex": Decimal("2000000000"),
        "eps_diluted": Decimal("-1"),
    },
    2023: {
        "revenue": Decimal("110000000000"),
        "cost_of_revenue": Decimal("85000000000"),
        "gross_profit": Decimal("25000000000"),
        "operating_income": Decimal("3000000000"),
        "net_income": Decimal("-2000000000"),
        "cfo": Decimal("8000000000"),
        "capex": Decimal("3000000000"),
        "eps_diluted": Decimal("-0.2"),
    },
    2025: {
        "revenue": Decimal("120000000000"),
        "cost_of_revenue": Decimal("90000000000"),
        "gross_profit": Decimal("30000000000"),
        "operating_income": Decimal("8000000000"),
        "net_income": Decimal("-3000000000"),
        "cfo": Decimal("10000000000"),
        "capex": Decimal("4000000000"),
        "eps_diluted": Decimal("-0.5"),
    },
}

# Restatement kept visible: EDGECO FY2023 revenue was first filed at 105e9, restated to 110e9.
_EDGECO_SUPERSEDED = {
    (2023, "revenue"): (Decimal("105000000000"), datetime.date(2023, 3, 1)),
}

# FULLCO operating income by FY index. Margin EXPANDS (0.25 -> 0.325) rather than staying a constant
# fraction of revenue, so ΔOpInc/ΔRev (operating leverage) is distinct from the point operating
# margin — a constant fraction would make the two numerically identical and untestable apart. FY2025
# is 130e9 (margin 0.325) so operating_margin assertions stay 0.325.
_FULLCO_OP_INCOME = (
    Decimal("50000000000"),  # FY2021, margin 0.250
    Decimal("70000000000"),  # FY2022, margin 0.280
    Decimal("90000000000"),  # FY2023, margin 0.300
    Decimal("105000000000"),  # FY2024, margin 0.300
    Decimal("130000000000"),  # FY2025, margin 0.325
)


def _accession(cik: int, fy: int) -> str:
    return f"{cik:010d}-{fy}-10K"


def _fullco_facts(i: int) -> dict[str, Decimal]:
    revenue = Decimal("200000000000") + Decimal("50000000000") * i
    eps = Decimal(3 + i)
    shares = Decimal("16000000000")
    gross_profit = revenue * Decimal("0.375")
    return {
        "revenue": revenue,
        "cost_of_revenue": revenue - gross_profit,
        "gross_profit": gross_profit,
        "operating_income": _FULLCO_OP_INCOME[i],
        "net_income": eps * shares,
        "eps_diluted": eps,
        "cfo": revenue * Decimal("0.30"),
        "capex": revenue * Decimal("0.05"),
        "shares_diluted": shares,
    }


def _add_facts(session: Session, cik: int, fy: int, facts: dict[str, Decimal]) -> None:
    period_end = datetime.date(fy, 12, 31)
    period_start = datetime.date(fy, 1, 1)
    filed = period_end + datetime.timedelta(days=60)
    accession = _accession(cik, fy)
    for concept, value in facts.items():
        superseded_value: Decimal | None = None
        superseded_filed: datetime.date | None = None
        if cik == EDGECO_CIK and (fy, concept) in _EDGECO_SUPERSEDED:
            superseded_value, superseded_filed = _EDGECO_SUPERSEDED[(fy, concept)]
        session.add(
            Fundamental(
                cik=cik,
                concept=concept,
                source_tag=f"us-gaap:{concept}",
                fiscal_year=fy,
                period_start=period_start,
                period_end=period_end,
                value=value,
                unit=_UNITS[concept],
                accession=accession,
                filed=filed,
                form="10-K",
                superseded_value=superseded_value,
                superseded_filed=superseded_filed,
            )
        )


def _add_prices(session: Session, cik: int) -> None:
    start = datetime.date(2026, 6, 1)
    for d in range(30):
        px = Decimal("150") + d
        session.add(
            Price(
                cik=cik,
                date=start + datetime.timedelta(days=d),
                open_=px,
                high=px + 1,
                low=px - 1,
                close=px,
                volume=1_000_000 + d,
                source="yfinance",
            )
        )


def seed_rich(session: Session) -> None:
    """FULLCO (happy path) + EDGECO (every guard), each with 30 days of prices (max close 179)."""
    session.add(Company(cik=FULLCO_CIK, ticker="FULL", name="Full Co."))
    session.add(Company(cik=EDGECO_CIK, ticker="EDGE", name="Edge Co."))

    for i, fy in enumerate((2021, 2022, 2023, 2024, 2025)):
        _add_facts(session, FULLCO_CIK, fy, _fullco_facts(i))
    for fy, facts in _EDGECO_FACTS.items():
        _add_facts(session, EDGECO_CIK, fy, facts)

    _add_prices(session, FULLCO_CIK)
    _add_prices(session, EDGECO_CIK)
    session.commit()
