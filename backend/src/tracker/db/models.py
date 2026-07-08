"""Frozen SQLAlchemy 2.0 schema (PLAN.md §3).

One row = one fact with provenance. Money is NUMERIC (never float); every temporal column is a
`date`. Natural-key UNIQUE constraints on every table. See the `tsv` block at the bottom for the
Postgres-only full-text column and why it is guarded rather than mapped.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    DDL,
    BigInteger,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint/index names across dialects (SQLite unit vs Postgres integration).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Money reaches hundreds of billions; keep 6 dp so per-share (EPS) rows stay exact.
_MONEY = Numeric(38, 6)
_PRICE = Numeric(18, 6)
_SHARES = Numeric(28, 4)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Company(Base):
    __tablename__ = "companies"

    # CIK is the real SEC natural key, not a surrogate — autoincrement off.
    cik: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ticker: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)


class Fundamental(Base):
    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint("cik", "concept", "fiscal_year", "period_end"),
        Index("ix_fundamentals_cik_concept_fiscal_year", "cik", "concept", "fiscal_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    concept: Mapped[str] = mapped_column(Text)
    source_tag: Mapped[str] = mapped_column(Text)  # us-gaap tag, "derived:…", or "…|split-adjusted"
    fiscal_year: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime.date | None] = mapped_column(Date)
    period_end: Mapped[datetime.date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(_MONEY)
    unit: Mapped[str] = mapped_column(Text)  # USD | USD/shares | shares
    accession: Mapped[str] = mapped_column(Text)
    filed: Mapped[datetime.date] = mapped_column(Date)
    form: Mapped[str] = mapped_column(Text)
    # Restatement kept VISIBLE (§5): latest-filed-wins overwrites value; prior value retained here.
    superseded_value: Mapped[Decimal | None] = mapped_column(_MONEY)
    superseded_filed: Mapped[datetime.date | None] = mapped_column(Date)


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("cik", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    date: Mapped[datetime.date] = mapped_column(Date)
    # attr `open_` -> SQL column "open" (avoid shadowing the builtin at the attribute level).
    open_: Mapped[Decimal] = mapped_column("open", _PRICE)
    high: Mapped[Decimal] = mapped_column(_PRICE)
    low: Mapped[Decimal] = mapped_column(_PRICE)
    close: Mapped[Decimal] = mapped_column(_PRICE)
    volume: Mapped[int] = mapped_column(BigInteger)  # single-name daily volume can exceed int32
    source: Mapped[str] = mapped_column(Text)  # yfinance | stooq


class Filing(Base):
    __tablename__ = "filings"

    accession: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    form: Mapped[str] = mapped_column(Text)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    period_end: Mapped[datetime.date] = mapped_column(Date)
    filed: Mapped[datetime.date] = mapped_column(Date)
    primary_doc_url: Mapped[str] = mapped_column(Text)


class FilingChunk(Base):
    __tablename__ = "filing_chunks"
    __table_args__ = (UniqueConstraint("accession", "item", "chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    accession: Mapped[str] = mapped_column(ForeignKey("filings.accession"))
    cik: Mapped[int] = mapped_column(Integer)  # plain int per §3 (accession is the FK, not cik)
    item: Mapped[str] = mapped_column(Text)  # 1A | 7 | FULL
    fiscal_year: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # `tsv` is intentionally NOT a mapped column here — see the dialect-guarded DDL below.


class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"
    __table_args__ = (UniqueConstraint("accession", "insider_name", "code", "shares", "filed"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[int] = mapped_column(ForeignKey("companies.cik"))
    accession: Mapped[str] = mapped_column(Text)  # plain text per §3 (no FK to filings)
    filed: Mapped[datetime.date] = mapped_column(Date)
    insider_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)  # P | S
    shares: Mapped[Decimal] = mapped_column(_SHARES)
    price: Mapped[Decimal | None] = mapped_column(_PRICE)
    value: Mapped[Decimal | None] = mapped_column(_MONEY)


# ---------------------------------------------------------------------------
# Dialect-guarded full-text column on filing_chunks.
#
# WHY this is DDL and not a mapped_column: `tsv` is a Postgres-only GENERATED STORED tsvector
# feeding full-text search (GIN + websearch_to_tsquery / ts_rank / ts_headline). SQLite — the
# unit-test dialect — has no tsvector type and no to_tsvector(), so this column cannot live in the
# ORM Table: a mapped_column emits its DDL on EVERY dialect, and unlike Index/Constraint a Column
# has no .ddl_if() to skip a dialect. So the base filing_chunks TABLE stays dialect-agnostic (seed
# inserts chunk rows under SQLite; the unit suite uses an ILIKE fallback), and tsv + its GIN index
# are bolted on by
# DDL that fires ONLY on Postgres, ONLY when the table is created. Postgres supports
# ADD COLUMN … GENERATED ALWAYS AS (…) STORED since PG12 (we target PG16). IF NOT EXISTS on both
# statements plus create_all(checkfirst=True) — which only fires after_create on a table's first
# creation — keep init_db idempotent. Retrieval services query tsv via raw text() on Postgres only.
# ---------------------------------------------------------------------------
_tsv_column_ddl = DDL(
    "ALTER TABLE filing_chunks "
    "ADD COLUMN IF NOT EXISTS tsv tsvector "
    "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
).execute_if(dialect="postgresql")

_tsv_gin_ddl = DDL(
    "CREATE INDEX IF NOT EXISTS ix_filing_chunks_tsv ON filing_chunks USING GIN (tsv)"
).execute_if(dialect="postgresql")

# Order matters: add the column before indexing it. after_create fires in registration order.
event.listen(FilingChunk.__table__, "after_create", _tsv_column_ddl)
event.listen(FilingChunk.__table__, "after_create", _tsv_gin_ddl)
