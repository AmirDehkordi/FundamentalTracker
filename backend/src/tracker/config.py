"""Application settings — all config from env / .env (CLAUDE.md: secrets only via env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The five-var config surface.

    Env matching is case-insensitive, so DATABASE_URL maps to `database_url` with no alias.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate unrelated shell/CI env vars
    )

    database_url: str
    llm_base_url: str
    # SecretStr keeps the key out of logs/repr/tracebacks; unwrap with .get_secret_value().
    llm_api_key: SecretStr
    llm_model: str
    sec_user_agent: str


@lru_cache
def get_settings() -> Settings:
    """Parse settings once. Values arrive from env/.env, which mypy can't see — hence the ignore."""
    return Settings()  # type: ignore[call-arg]
