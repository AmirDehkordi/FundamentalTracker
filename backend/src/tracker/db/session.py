"""Engine + session factory, created lazily.

`create_engine` is already lazy about opening connections, but *constructing* it reads settings.
Doing that inside `get_engine()` (cached) means importing this module never requires DATABASE_URL —
so the unit suite, which overrides `get_session` with a SQLite session, needs no Postgres env at
all, and CI (no committed .env) imports the app cleanly. Real DB use (scripts, live endpoints) reads
settings on first call.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tracker.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False so objects handed to services/api stay usable after commit; autoflush
    # off for predictable query timing.
    return sessionmaker(bind=get_engine(), class_=Session, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a request-scoped Session, always closed."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts/ingestion: commit on success, rollback on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
