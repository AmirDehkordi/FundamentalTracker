"""Settings (config.py) and the lazy engine/session helpers (db/session.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from tracker.config import Settings, get_settings


def test_settings_masks_the_api_key() -> None:
    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost:5433/db",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-secret-value",  # type: ignore[arg-type]
        llm_model="gpt-5.5",
        sec_user_agent="Test agent test@example.com",
    )
    assert isinstance(s.llm_api_key, SecretStr)
    assert s.llm_api_key.get_secret_value() == "sk-secret-value"
    assert "sk-secret-value" not in repr(s)  # SecretStr keeps it out of logs/repr


def _settings(**overrides: str) -> Settings:
    base = {
        "database_url": "sqlite://",
        "llm_base_url": "http://example.test/v1",
        "llm_api_key": "sk-test",
        "llm_model": "gpt-test",
        "sec_user_agent": "unit-test agent",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_universe_tickers_defaults_to_the_five() -> None:
    assert _settings().universe_tickers == ["NVDA", "MSFT", "AAPL", "GOOGL", "ETN"]


def test_universe_tickers_parses_normalises_and_dedupes() -> None:
    # lower-case, padding, blanks and a duplicate all normalise to a clean ordered list.
    assert _settings(universe=" aapl, nvda ,,aapl,").universe_tickers == ["AAPL", "NVDA"]


def test_blank_sec_user_agent_is_rejected() -> None:
    # SEC bans requests with a blank UA; the misconfig must fail fast at settings load, not live.
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        _settings(sec_user_agent="")


def _set_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_BASE_URL", "http://example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("SEC_USER_AGENT", "unit-test agent")


def test_session_helpers_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A file-backed SQLite so the create_all connection and the session connection share state.
    db_url = f"sqlite+pysqlite:///{tmp_path / 'unit.db'}"
    _set_env(monkeypatch, db_url)

    from tracker.db import session as sess
    from tracker.db.models import Base, Company

    # Env overrides the committed .env; clear the caches so these helpers see it.
    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    try:
        Base.metadata.create_all(sess.get_engine())

        with sess.session_scope() as write:
            write.add(Company(cik=1, ticker="ZZZ", name="Zeta"))

        gen = sess.get_session()
        read = next(gen)
        try:
            got = read.get(Company, 1)
            assert got is not None and got.ticker == "ZZZ"
        finally:
            gen.close()
    finally:
        sess.get_engine.cache_clear()
        sess.get_sessionmaker.cache_clear()
        get_settings.cache_clear()


def test_session_scope_rolls_back_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}"
    _set_env(monkeypatch, db_url)

    from tracker.db import session as sess
    from tracker.db.models import Base, Company

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    try:
        Base.metadata.create_all(sess.get_engine())
        with pytest.raises(RuntimeError):
            with sess.session_scope() as write:
                write.add(Company(cik=2, ticker="AAA", name="Alpha"))
                raise RuntimeError("boom")

        gen = sess.get_session()
        read = next(gen)
        try:
            assert read.get(Company, 2) is None  # rolled back
        finally:
            gen.close()
    finally:
        sess.get_engine.cache_clear()
        sess.get_sessionmaker.cache_clear()
        get_settings.cache_clear()
