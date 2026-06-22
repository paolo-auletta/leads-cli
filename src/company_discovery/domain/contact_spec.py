from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from company_discovery.domain.models import DomainModel
from company_discovery.services.normalization import canonical_domain


ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ContactCompanySource(DomainModel):
    enrichment_run_id: str = Field(min_length=1)
    bucket: Literal["ready", "review", "all"] = "ready"
    domains: list[str] = Field(default_factory=list)

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            domain = canonical_domain(value)
            if domain is None:
                raise ValueError(f"invalid company domain: {value}")
            if domain not in normalized:
                normalized.append(domain)
        return normalized


class ContactRoleTarget(DomainModel):
    key: str = Field(min_length=2, max_length=64)
    labels: list[str] = Field(min_length=1, max_length=12)
    max_per_company: int = Field(default=1, ge=1, le=10)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if not ROLE_KEY_PATTERN.fullmatch(normalized):
            raise ValueError("role key must use lowercase letters, numbers, and underscores")
        return normalized

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        labels: list[str] = []
        for value in values:
            label = " ".join(value.lower().split())
            if len(label) < 2:
                raise ValueError("role labels cannot be empty")
            if label not in labels:
                labels.append(label)
        return labels


class ContactSearchSpec(DomainModel):
    version: Literal[1] = 1
    company_source: ContactCompanySource
    roles: list[ContactRoleTarget] = Field(min_length=1, max_length=20)
    company_limit: int | None = Field(default=None, ge=1, le=1000)
    contact_limit: int | None = Field(default=None, ge=1, le=10000)
    current_only: bool = True
    require_role_match: bool = True
    memory_freshness_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def validate_unique_roles(self) -> "ContactSearchSpec":
        keys = [role.key for role in self.roles]
        if len(keys) != len(set(keys)):
            raise ValueError("role keys must be unique")
        return self

    @classmethod
    def from_file(cls, path: Path) -> "ContactSearchSpec":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        return cls.model_validate(payload)

