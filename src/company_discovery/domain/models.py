from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FitVerdict(StrEnum):
    GOOD = "good_fit"
    POSSIBLE = "possible_fit"
    BAD = "bad_fit"


class MatchVerdict(StrEnum):
    YES = "yes"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    NO = "no"


class ExclusionVerdict(StrEnum):
    YES = "yes"
    POSSIBLE = "possible"
    NO = "no"


class CandidateBucket(StrEnum):
    SELECTED = "selected"
    RESERVE = "reserve"
    REJECTED = "rejected"


class QueryPlan(DomainModel):
    queries: list[str] = Field(min_length=1, max_length=12)
    rationale: str


class ExaSearchResult(DomainModel):
    query: str
    position: int = Field(ge=1)
    title: str
    url: str
    text: str | None = None
    published_date: str | None = None
    exa_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceSighting(DomainModel):
    query: str
    url: str
    title: str
    text: str | None = None
    exa_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedCandidate(DomainModel):
    company_name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    dedupe_key: str = Field(min_length=1)
    vertical: str | None = None
    country: str | None = None
    state: str | None = None
    employee_min: int | None = Field(default=None, ge=1)
    employee_max: int | None = Field(default=None, ge=1)
    ownership_type: str | None = None
    excluded: bool = False
    sightings: list[SourceSighting] = Field(default_factory=list)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CandidateEvaluation(DomainModel):
    company_name: str
    domain: str
    fit: FitVerdict
    vertical_match: MatchVerdict
    geography_match: MatchVerdict
    size_match: MatchVerdict
    excluded: ExclusionVerdict
    reason: str = Field(min_length=1)
    reason_codes: list[str]
    evidence: list[str]
    inferred_vertical: str | None
    inferred_country: str | None
    inferred_state: str | None
    inferred_employee_min: int | None = Field(ge=1)
    inferred_employee_max: int | None = Field(ge=1)
    inferred_ownership_type: str | None
    target_vertical: str | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> "CandidateEvaluation":
        hard_mismatch = any(
            verdict == MatchVerdict.NO
            for verdict in (self.vertical_match, self.geography_match, self.size_match)
        )
        if self.fit == FitVerdict.GOOD and (
            hard_mismatch or self.excluded != ExclusionVerdict.NO
        ):
            raise ValueError("good_fit cannot contain a hard mismatch or exclusion")
        if self.excluded == ExclusionVerdict.YES and self.fit != FitVerdict.BAD:
            raise ValueError("an excluded candidate must be bad_fit")
        if (
            self.inferred_employee_min is not None
            and self.inferred_employee_max is not None
            and self.inferred_employee_min > self.inferred_employee_max
        ):
            raise ValueError("inferred employee minimum cannot exceed maximum")
        return self


class BucketedCandidate(DomainModel):
    candidate: NormalizedCandidate
    evaluation: CandidateEvaluation
    bucket: CandidateBucket
    source: str
    target_vertical: str | None = None


class RunSummary(DomainModel):
    memory_matched: int = 0
    memory_reused: int = 0
    memory_rechecked: int = 0
    memory_skipped: int = 0
    external_gap: int = 0
    queries_generated: int = 0
    raw_results: int = 0
    unique_candidates: int = 0
    hygiene_rejected: int = 0
    selected: int = 0
    reserve: int = 0
    rejected: int = 0


class RunResult(DomainModel):
    run_id: str
    summary: RunSummary
    queries: list[str]
    candidates: list[BucketedCandidate]
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class IndependenceStatus(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class InheritedFieldStatus(StrEnum):
    INHERITED = "inherited"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"


class EnrichmentOutcome(StrEnum):
    READY = "enriched_ready"
    GAPS = "enriched_with_gaps"
    INDEPENDENCE_UNCONFIRMED = "independence_unconfirmed"
    IDENTITY_CONFLICT = "identity_conflict"
    GEOGRAPHY_CONFLICT = "geography_conflict"
    FIT_CONFLICT = "fit_conflict"
    FAILED = "enrichment_failed"


class WebsitePage(DomainModel):
    url: str
    title: str = ""
    text: str
    page_type: str = "other"


class PhoneObservation(DomainModel):
    value: str
    label: str | None = None
    source_url: str


class LocationObservation(DomainModel):
    street_address: str
    city: str
    state: str
    zip: str
    country: str = "US"
    label: str | None = None
    source_url: str


class OwnershipSignal(DomainModel):
    kind: str
    statement: str
    source_url: str


class EnrichmentExtraction(DomainModel):
    observed_company_name: str | None = None
    identity_conflict: bool = False
    identity_conflict_reason: str | None = None
    phones: list[PhoneObservation] = Field(default_factory=list)
    locations: list[LocationObservation] = Field(default_factory=list)
    ownership_signals: list[OwnershipSignal] = Field(default_factory=list)


class PhoneFact(DomainModel):
    value: str
    display_value: str
    source: str
    source_url: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LocationFact(DomainModel):
    street_address: str
    city: str
    state: str
    zip: str
    country: str = "US"
    source: str
    source_url: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IndependenceFact(DomainModel):
    status: IndependenceStatus
    evidence: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    signal_kinds: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EnrichmentProfile(DomainModel):
    phone: PhoneFact | None = None
    location: LocationFact | None = None
    independence: IndependenceFact | None = None


class EnrichmentItem(DomainModel):
    company_id: int
    discovery: dict[str, Any]
    enrichment: EnrichmentProfile
    inherited_status: dict[str, InheritedFieldStatus]
    outcome: EnrichmentOutcome
    conflicts: list[str] = Field(default_factory=list)
    review_flags: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class EnrichmentSummary(DomainModel):
    processed: int = 0
    inherited_facts: int = 0
    memory_profiles_reused: int = 0
    websites_fetched: int = 0
    fallback_searches: int = 0
    ready: int = 0
    review: int = 0
    blocked: int = 0
    failed: int = 0


class EnrichmentRunResult(DomainModel):
    run_id: str
    discovery_run_id: str
    summary: EnrichmentSummary
    items: list[EnrichmentItem]
    artifact_paths: dict[str, str] = Field(default_factory=dict)
