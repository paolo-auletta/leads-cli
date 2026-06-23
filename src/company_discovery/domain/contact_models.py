from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from company_discovery.domain.models import DomainModel, ExaSearchResult


class ContactVerdict(StrEnum):
    ACCEPTED = "accepted"
    REVIEW = "review"
    REJECTED = "rejected"


class EvidenceVerdict(StrEnum):
    YES = "yes"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    NO = "no"


class ContactAssessment(DomainModel):
    full_name: str = Field(min_length=3)
    title: str = Field(min_length=2)
    linkedin_url: str | None = None
    source_urls: list[str] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    current_company_match: EvidenceVerdict
    role_match: EvidenceVerdict
    identity_clear: bool
    verdict: ContactVerdict
    reason: str = Field(min_length=3)

    @field_validator("full_name", "title")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class ContactAssessmentBatch(DomainModel):
    candidates: list[ContactAssessment] = Field(default_factory=list, max_length=30)


class ContactCandidate(DomainModel):
    company_id: int
    company_name: str
    company_domain: str
    full_name: str
    normalized_name: str
    identity_key: str
    title: str
    linkedin_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContactDiscoveryItem(DomainModel):
    candidate_id: int
    candidate: ContactCandidate
    role_key: str
    verdict: ContactVerdict
    reason: str
    current_company_match: EvidenceVerdict
    role_match: EvidenceVerdict
    identity_clear: bool
    source: str


class ContactDiscoverySummary(DomainModel):
    companies_loaded: int = 0
    memory_reused: int = 0
    role_gaps: int = 0
    queries_run: int = 0
    raw_results: int = 0
    unique_people: int = 0
    accepted: int = 0
    review: int = 0
    rejected: int = 0


class ContactDiscoveryResult(DomainModel):
    run_id: str
    source_enrichment_run_id: str
    summary: ContactDiscoverySummary
    items: list[ContactDiscoveryItem]
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class ContactSearchBatch(DomainModel):
    company_name: str
    company_domain: str
    role_key: str
    role_labels: list[str]
    results: list[ExaSearchResult]


class ContactEnrichmentOutcome(StrEnum):
    READY = "ready"
    REVIEW = "review"
    BLOCKED = "blocked"


class ApolloPersonRequest(DomainModel):
    candidate_id: int
    first_name: str
    last_name: str
    full_name: str
    company_name: str
    company_domain: str
    linkedin_url: str | None = None


class ApolloPersonMatch(DomainModel):
    candidate_id: int
    person_found: bool
    full_name: str | None = None
    linkedin_url: str | None = None
    title: str | None = None
    organization_name: str | None = None
    organization_domain: str | None = None
    email: str | None = None
    email_status: str | None = None
    phones: list[str] = Field(default_factory=list)
    apollo_person_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ApolloBatchResult(DomainModel):
    matches: list[ApolloPersonMatch] = Field(default_factory=list)
    request_id: str | None = None
    pending: bool = False


class ContactChannelProfile(DomainModel):
    email_requested: bool = False
    phone_requested: bool = False
    email: str | None = None
    email_status: str | None = None
    phone: str | None = None
    apollo_person_id: str | None = None
    apollo_linkedin_url: str | None = None
    apollo_company_name: str | None = None
    apollo_company_domain: str | None = None
    apollo_title: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContactEnrichmentItem(DomainModel):
    candidate_id: int
    discovery: dict[str, Any]
    channels: ContactChannelProfile
    outcome: ContactEnrichmentOutcome
    review_flags: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class ContactEnrichmentSummary(DomainModel):
    contacts_loaded: int = 0
    memory_reused: int = 0
    apollo_requests: int = 0
    apollo_batches: int = 0
    async_polls: int = 0
    ready: int = 0
    review: int = 0
    blocked: int = 0


class ContactEnrichmentResult(DomainModel):
    run_id: str
    source_contact_run_id: str
    summary: ContactEnrichmentSummary
    items: list[ContactEnrichmentItem]
    artifact_paths: dict[str, str] = Field(default_factory=dict)
