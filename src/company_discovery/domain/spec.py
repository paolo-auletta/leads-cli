from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VerticalMode(StrEnum):
    KNOWN = "known"
    EXPLORATORY = "exploratory"


class NoveltyMode(StrEnum):
    UNUSED_MEMORY = "unused_memory"
    ONLY_NEW = "only_new"
    FULL_MEMORY = "full_memory"


class BalanceMode(StrEnum):
    SOFT = "soft"
    STRICT = "strict"
    NONE = "none"


class VerticalSpec(StrictModel):
    mode: VerticalMode
    key: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1)
    seed_terms: list[str] = Field(default_factory=list)
    anti_terms: list[str] = Field(default_factory=list)

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("seed_terms", "anti_terms")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_mode(self) -> "VerticalSpec":
        if self.mode == VerticalMode.EXPLORATORY and not self.seed_terms:
            raise ValueError("exploratory verticals require at least one seed term")
        return self


class GeographySpec(StrictModel):
    country: str = Field(default="US", min_length=2, max_length=2)
    states: list[str] = Field(default_factory=list)

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("states")
    @classmethod
    def normalize_states(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.upper() for value in values))

    @model_validator(mode="after")
    def validate_states(self) -> "GeographySpec":
        if self.country == "US":
            invalid = sorted(set(self.states) - US_STATE_CODES)
            if invalid:
                raise ValueError(f"invalid US state codes: {', '.join(invalid)}")
        return self


class CompanySizeSpec(StrictModel):
    employee_min: int | None = Field(default=None, ge=1)
    employee_max: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "CompanySizeSpec":
        if (
            self.employee_min is not None
            and self.employee_max is not None
            and self.employee_min > self.employee_max
        ):
            raise ValueError("employee_min cannot exceed employee_max")
        return self

    @property
    def is_unbounded(self) -> bool:
        return self.employee_min is None and self.employee_max is None


class IncludeSpec(StrictModel):
    keywords: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)

    @field_validator("keywords", "subtypes")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


class OwnershipSignalKind(StrEnum):
    FAMILY_OWNED = "family_owned"
    FRANCHISE = "franchise"
    PARENT = "parent"
    SUBSIDIARY = "subsidiary"
    DIVISION = "division"
    ACQUIRED = "acquired"


class StructuredExcludeSpec(StrictModel):
    ownership_signals: list[OwnershipSignalKind] = Field(default_factory=list)

    @field_validator("ownership_signals", mode="before")
    @classmethod
    def normalize_ownership_signals(cls, values: object) -> object:
        if not isinstance(values, list):
            return values
        return list(
            dict.fromkeys(
                value.strip().lower() if isinstance(value, str) else value
                for value in values
            )
        )


class ExcludeSpec(StrictModel):
    keywords: list[str] = Field(default_factory=list)
    ownership_types: list[str] = Field(default_factory=list)
    company_patterns: list[str] = Field(default_factory=list)
    structured: StructuredExcludeSpec = Field(default_factory=StructuredExcludeSpec)

    @field_validator("keywords", "ownership_types", "company_patterns")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


class CompanySearchSpec(StrictModel):
    version: Literal[1]
    count: int = Field(ge=1, le=1000)
    verticals: list[VerticalSpec] = Field(
        min_length=1,
        validation_alias=AliasChoices("verticals", "vertical"),
    )
    geography: GeographySpec = Field(default_factory=GeographySpec)
    company_size: CompanySizeSpec = Field(default_factory=CompanySizeSpec)
    include: IncludeSpec = Field(default_factory=IncludeSpec)
    exclude: ExcludeSpec = Field(default_factory=ExcludeSpec)
    novelty_mode: NoveltyMode = NoveltyMode.UNUSED_MEMORY
    reserve_ratio: float = Field(default=0.5, ge=0, le=2)
    balance_mode: BalanceMode = BalanceMode.SOFT

    @field_validator("verticals", mode="before")
    @classmethod
    def accept_single_vertical(cls, value: object) -> object:
        return [value] if isinstance(value, dict) else value

    @field_validator("novelty_mode", mode="before")
    @classmethod
    def migrate_legacy_novelty_modes(cls, value: object) -> object:
        # Keep persisted v1 specs and old agent-generated files runnable.
        return {
            "prefer_new": NoveltyMode.UNUSED_MEMORY,
            "allow_known": NoveltyMode.FULL_MEMORY,
        }.get(value, value)

    @field_validator("verticals")
    @classmethod
    def unique_verticals(cls, values: list[VerticalSpec]) -> list[VerticalSpec]:
        keys = [vertical.key for vertical in values]
        if len(keys) != len(set(keys)):
            raise ValueError("vertical keys must be unique")
        return values

    @classmethod
    def from_file(cls, path: Path) -> "CompanySearchSpec":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"spec file does not exist: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"spec is not valid JSON: {exc}") from exc
        return cls.model_validate(payload)

    @property
    def is_national(self) -> bool:
        return not self.geography.states

    @property
    def reserve_count(self) -> int:
        return round(self.count * self.reserve_ratio)

    @property
    def vertical(self) -> VerticalSpec:
        if len(self.verticals) != 1:
            raise ValueError("single-vertical operation requires exactly one vertical")
        return self.verticals[0]

    def lane_spec(self, vertical: VerticalSpec, count: int) -> "CompanySearchSpec":
        return self.model_copy(update={"verticals": [vertical], "count": max(1, count)})

    @property
    def vertical_quotas(self) -> dict[str, int]:
        base, remainder = divmod(self.count, len(self.verticals))
        return {
            vertical.key: base + (1 if index < remainder else 0)
            for index, vertical in enumerate(self.verticals)
        }

    @property
    def missing_constraints(self) -> list[str]:
        missing: list[str] = []
        if self.is_national:
            missing.append("national search mode used")
        if self.company_size.is_unbounded:
            missing.append("no size filter applied")
        if not any(
            (
                self.exclude.keywords,
                self.exclude.ownership_types,
                self.exclude.company_patterns,
                self.exclude.structured.ownership_signals,
            )
        ):
            missing.append("no custom exclusions applied")
        if any(vertical.mode == VerticalMode.EXPLORATORY for vertical in self.verticals):
            missing.append("exploratory vertical mode used")
        return missing
