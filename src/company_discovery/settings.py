from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from company_discovery.runtime import (
    configure_workspace_logging,
    default_workspace_root,
    ensure_workspace,
    load_local_settings,
    read_workspace_pointer,
)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and the local workspace."""

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    leads_home: Path = Field(
        default_factory=default_workspace_root,
        validation_alias=AliasChoices("LEADS_HOME", "COMPANY_DISCOVERY_HOME"),
    )
    database_url: str | None = None

    llm_provider: str = "openai"
    exa_api_key: str | None = None
    exa_base_url: str = "https://api.exa.ai"
    exa_timeout_seconds: float = 60.0
    exa_results_per_query: int = Field(default=5, ge=1, le=100)

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5-mini"
    llm_timeout_seconds: float = 90.0
    llm_max_tokens: int = Field(default=4096, ge=256, le=65536)
    llm_response_format: Literal["auto", "json_schema", "json_object"] = "auto"

    query_count: int = Field(default=8, ge=1, le=20)

    enrichment_freshness_days: int = Field(default=180, ge=1, le=3650)
    enrichment_website_timeout_seconds: float = Field(default=20.0, ge=1, le=120)
    enrichment_max_pages: int = Field(default=4, ge=1, le=10)
    enrichment_fallback_results: int = Field(default=5, ge=1, le=20)

    contact_results_per_query: int = Field(default=10, ge=1, le=50)

    apollo_api_key: str | None = None
    apollo_base_url: str = "https://api.apollo.io"
    apollo_timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    apollo_webhook_url: str | None = None
    apollo_enrichment_freshness_days: int = Field(default=14, ge=1, le=365)
    apollo_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=60)
    apollo_poll_timeout_seconds: float = Field(default=120.0, ge=1, le=1800)

    @property
    def company_discovery_home(self) -> Path:
        """Backward-compatible internal alias for the leads workspace root."""
        return self.leads_home

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
        database_path = self.company_discovery_home / "data" / "company_memory.db"
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

    @property
    def config_dir(self) -> Path:
        return self.company_discovery_home / "config"

    @property
    def specs_dir(self) -> Path:
        return self.company_discovery_home / "specs"

    @property
    def logs_dir(self) -> Path:
        return self.company_discovery_home / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.company_discovery_home / "backups"

    @property
    def skills_dir(self) -> Path:
        return self.company_discovery_home / "skills"

    def prepare_directories(self) -> None:
        ensure_workspace(self.company_discovery_home)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    bootstrap = Settings()
    root = _configured_workspace_root(bootstrap)
    local_settings = _without_env_overrides(load_local_settings(root))
    settings = Settings(**{"LEADS_HOME": root, **local_settings})
    settings.prepare_directories()
    configure_workspace_logging(settings.company_discovery_home)
    return settings


def _configured_workspace_root(bootstrap: Settings) -> Path:
    if any(name in os.environ for name in _env_names_for_field("leads_home")):
        return bootstrap.company_discovery_home
    return read_workspace_pointer() or default_workspace_root()


def _without_env_overrides(values: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in values.items()
        if not any(name in os.environ for name in _env_names_for_field(key))
    }


def _env_names_for_field(field_name: str) -> tuple[str, ...]:
    if field_name == "leads_home":
        return "LEADS_HOME", "COMPANY_DISCOVERY_HOME"
    return (field_name.upper(),)
