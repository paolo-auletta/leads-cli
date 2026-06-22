from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

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
