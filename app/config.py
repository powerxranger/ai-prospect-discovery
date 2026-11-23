from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every secret comes from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Prospect Discovery API"
    environment: str = "local"
    log_level: str = "INFO"

    llm_provider: Literal["gemini", "groq", "openai", "none"] = "gemini"
    llm_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    request_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    search_concurrency: int = Field(default=4, ge=1, le=16)
    max_search_results_per_query: int = Field(default=5, ge=1, le=20)
    max_candidates: int = Field(default=24, ge=1, le=100)
    max_profile_fetches: int = Field(default=10, ge=0, le=50)
    max_redirects: int = Field(default=3, ge=0, le=5)
    safe_fetch_max_bytes: int = Field(default=250_000, ge=1_000)
    safe_fetch_max_chars: int = Field(default=12_000, ge=500)
    cache_ttl_seconds: int = Field(default=900, ge=0)
    cache_max_entries: int = Field(default=256, ge=1)
    llm_max_retries: int = Field(default=1, ge=0, le=3)

    def active_llm_key(self) -> SecretStr | None:
        if self.llm_provider == "gemini":
            return self.gemini_api_key
        if self.llm_provider == "groq":
            return self.groq_api_key
        if self.llm_provider == "openai":
            return self.openai_api_key
        return None

    def configured_secrets(self) -> list[str]:
        values: list[str] = []
        for secret in (
            self.gemini_api_key,
            self.groq_api_key,
            self.openai_api_key,
            self.tavily_api_key,
        ):
            if secret is None:
                continue
            value = secret.get_secret_value()
            if len(value) >= 8:
                values.append(value)
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
