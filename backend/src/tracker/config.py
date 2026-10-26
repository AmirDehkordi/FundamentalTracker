"""Application settings — all config from env / .env (CLAUDE.md: secrets only via env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config surface — five required secrets/URLs plus the ingestion universe.

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
    # SEC bans requests with a blank/absent UA; fail fast at load rather than get throttled live.
    sec_user_agent: str = Field(min_length=1)
    # The tracked universe. Kept a comma-separated str (not list[str]) so a plain UNIVERSE env var
    # works — pydantic-settings otherwise wants JSON for complex types. Swapping a ticker is a
    # config edit + re-ingest, never a code change. Default is the five.
    universe: str = "NVDA,MSFT,AAPL,GOOGL,ETN"

    @property
    def universe_tickers(self) -> list[str]:
        """Configured tickers, upper-cased and de-duplicated in declared order."""
        seen: dict[str, None] = {}
        for raw in self.universe.split(","):
            ticker = raw.strip().upper()
            if ticker:
                seen.setdefault(ticker, None)
        return list(seen)


@lru_cache
def get_settings() -> Settings:
    """Parse settings once. Values arrive from env/.env, which mypy can't see — hence the ignore."""
    return Settings()  # type: ignore[call-arg]
