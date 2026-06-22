from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    company_discovery_home: Path = Field(default=Path(".company-discovery"))
    database_url: str | None = None

    exa_api_key: str | None = None
    exa_base_url: str = "https://api.exa.ai"
    exa_timeout_seconds: float = 60.0
    exa_results_per_query: int = Field(default=25, ge=1, le=100)

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5-mini"
    llm_timeout_seconds: float = 90.0
    llm_max_tokens: int = Field(default=4096, ge=256, le=65536)
    llm_response_format: Literal["auto", "json_schema", "json_object"] = "auto"

    query_count: int = Field(default=8, ge=6, le=12)

    enrichment_freshness_days: int = Field(default=180, ge=1, le=3650)
    enrichment_website_timeout_seconds: float = Field(default=20.0, ge=1, le=120)
    enrichment_max_pages: int = Field(default=4, ge=1, le=10)
    enrichment_fallback_results: int = Field(default=5, ge=1, le=20)

    contact_results_per_query: int = Field(default=10, ge=1, le=50)

    @property
    def resolved_llm_response_format(self) -> Literal["json_schema", "json_object"]:
        if self.llm_response_format != "auto":
            return self.llm_response_format
        hostname = (urlparse(self.llm_base_url).hostname or "").lower()
        return "json_schema" if hostname in {"api.openai.com", "openai.com"} else "json_object"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = self.company_discovery_home / "company_memory.db"
        return f"sqlite:///{database_path.resolve()}"

    @property
    def sqlite_database_path(self) -> Path | None:
        """Return the configured on-disk SQLite path, if there is one."""
        prefix = "sqlite:///"
        url = self.resolved_database_url
        if not url.startswith(prefix):
            return None
        raw_path = url.removeprefix(prefix).partition("?")[0]
        if not raw_path or raw_path == ":memory:":
            return None
        return Path(raw_path)

    @property
    def artifacts_dir(self) -> Path:
        return self.company_discovery_home / "runs"

    def prepare_directories(self) -> None:
        self.company_discovery_home.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
