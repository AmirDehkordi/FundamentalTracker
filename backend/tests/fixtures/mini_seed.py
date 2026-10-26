"""Deterministic fixture data for unit tests.

Dialect-agnostic: never writes `filing_chunks.tsv` (generated on Postgres, absent on SQLite), and
magnitudes are round base-10 so SQLite's float round-trip of NUMERIC stays exact. Fake CIKs/values —
nothing here is real data.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from tracker.db.models import Company, Filing, FilingChunk, Fundamental, Price

# (cik, ticker, name, fy-end month, fy-end day)
_COMPANIES = [
    (320193, "AAPL", "Apple Inc.", 9, 27),
    (1045810, "NVDA", "NVIDIA Corporation", 1, 25),
]
_FISCAL_YEARS = (2023, 2024, 2025)


def _accession(cik: int, fy: int) -> str:
    return f"{cik:010d}-{fy}-10K"


def seed_minimal(session: Session) -> None:
    """2 companies, 3 FYs of fundamentals each, 30 days of prices, 4 chunks (+ parent filings)."""
    for cik, ticker, name, _month, _day in _COMPANIES:
        session.add(Company(cik=cik, ticker=ticker, name=name))

    for cik, _ticker, _name, month, day in _COMPANIES:
        for i, fy in enumerate(_FISCAL_YEARS):
            period_end = datetime.date(fy, month, day)
            period_start = datetime.date(fy - 1, month, day) + datetime.timedelta(days=1)
            filed = period_end + datetime.timedelta(days=35)
            accn = _accession(cik, fy)
            scale = Decimal(i + 1)
            session.add(
                Filing(
                    accession=accn,
                    cik=cik,
                    form="10-K",
                    fiscal_year=fy,
                    period_end=period_end,
                    filed=filed,
                    primary_doc_url=f"https://www.sec.gov/Archives/{accn}.htm",
                )
            )
            session.add_all(
                [
                    Fundamental(
                        cik=cik,
                        concept="revenue",
                        source_tag="us-gaap:Revenues",
                        fiscal_year=fy,
                        period_start=period_start,
                        period_end=period_end,
                        value=Decimal("100000000000") * scale,
                        unit="USD",
                        accession=accn,
                        filed=filed,
                        form="10-K",
                    ),
                    Fundamental(
                        cik=cik,
                        concept="net_income",
                        source_tag="us-gaap:NetIncomeLoss",
                        fiscal_year=fy,
                        period_start=period_start,
                        period_end=period_end,
                        value=Decimal("25000000000") * scale,
                        unit="USD",
                        accession=accn,
                        filed=filed,
                        form="10-K",
                    ),
                    Fundamental(
                        cik=cik,
                        concept="eps_diluted",
                        source_tag="us-gaap:EarningsPerShareDiluted",
                        fiscal_year=fy,
                        period_start=period_start,
                        period_end=period_end,
                        value=Decimal("5") + i,
                        unit="USD/shares",
                        accession=accn,
                        filed=filed,
                        form="10-K",
                    ),
                ]
            )

    start = datetime.date(2026, 6, 1)
    for cik, _ticker, _name, _month, _day in _COMPANIES:
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

    aapl_fy2025 = _accession(320193, 2025)
    for idx in range(4):
        session.add(
            FilingChunk(
                accession=aapl_fy2025,
                cik=320193,
                item="1A",
                fiscal_year=2025,
                chunk_index=idx,
                text=f"Risk factor paragraph {idx}: supply constraints and demand.",
            )
        )

    session.commit()
