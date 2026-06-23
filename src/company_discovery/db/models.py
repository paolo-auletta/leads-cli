from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DiscoveryRunRow(Base):
    __tablename__ = "company_discovery_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    spec_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_spec_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_paths: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    queries: Mapped[list[DiscoveryQueryRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="DiscoveryQueryRow.query_order"
    )
    evaluations: Mapped[list[CandidateEvaluationRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class DiscoveryQueryRow(Base):
    __tablename__ = "company_discovery_queries"
    __table_args__ = (UniqueConstraint("run_id", "query_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("company_discovery_runs.id", ondelete="CASCADE"), index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_order: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_dollars: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[DiscoveryRunRow] = relationship(back_populates="queries")
    raw_results: Mapped[list[RawResultRow]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class RawResultRow(Base):
    __tablename__ = "company_discovery_raw_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("company_discovery_runs.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("company_discovery_queries.id", ondelete="CASCADE"), index=True)
    result_position: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    query: Mapped[DiscoveryQueryRow] = relationship(back_populates="raw_results")


class CompanyCandidateRow(Base):
    __tablename__ = "company_candidates"
    __table_args__ = (
        Index("ix_company_candidates_market", "vertical", "country", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    vertical: Mapped[str | None] = mapped_column(String(128), index=True)
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    state: Mapped[str | None] = mapped_column(String(8), index=True)
    employee_min: Mapped[int | None] = mapped_column(Integer)
    employee_max: Mapped[int | None] = mapped_column(Integer)
    ownership_type: Mapped[str | None] = mapped_column(String(128), index=True)
    prior_bucket: Mapped[str | None] = mapped_column(String(32), index=True)
    prior_reason: Mapped[str | None] = mapped_column(Text)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evaluations: Mapped[list[CandidateEvaluationRow]] = relationship(back_populates="candidate")


class CandidateEvaluationRow(Base):
    __tablename__ = "company_candidate_evaluations"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("company_discovery_runs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("company_candidates.id"), index=True)
    evaluation_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fit_outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[DiscoveryRunRow] = relationship(back_populates="evaluations")
    candidate: Mapped[CompanyCandidateRow] = relationship(back_populates="evaluations")


class EnrichmentRunRow(Base):
    __tablename__ = "company_enrichment_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discovery_run_id: Mapped[str] = mapped_column(
        ForeignKey("company_discovery_runs.id"), nullable=False, index=True
    )
    bucket: Mapped[str] = mapped_column(String(32), nullable=False, default="selected")
    options_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_paths: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[EnrichmentItemRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EnrichmentItemRow.id"
    )


class EnrichmentItemRow(Base):
    __tablename__ = "company_enrichment_items"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("company_enrichment_runs.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(ForeignKey("company_candidates.id"), index=True)
    discovery_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enrichment_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inherited_status: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    conflicts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trace_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[EnrichmentRunRow] = relationship(back_populates="items")


class EnrichmentFactRow(Base):
    __tablename__ = "company_enrichment_facts"
    __table_args__ = (Index("ix_enrichment_fact_latest", "candidate_id", "fact_kind", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("company_candidates.id"), index=True)
    enrichment_run_id: Mapped[str] = mapped_column(ForeignKey("company_enrichment_runs.id"), index=True)
    fact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ContactDiscoveryRunRow(Base):
    __tablename__ = "contact_discovery_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    enrichment_run_id: Mapped[str] = mapped_column(
        ForeignKey("company_enrichment_runs.id"), nullable=False, index=True
    )
    spec_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_spec_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_paths: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    queries: Mapped[list[ContactDiscoveryQueryRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ContactDiscoveryQueryRow.id",
    )
    evaluations: Mapped[list[ContactEvaluationRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ContactDiscoveryQueryRow(Base):
    __tablename__ = "contact_discovery_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("contact_discovery_runs.id", ondelete="CASCADE"), index=True
    )
    company_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_dollars: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    raw_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[ContactDiscoveryRunRow] = relationship(back_populates="queries")


class ContactCandidateRow(Base):
    __tablename__ = "contact_candidates"
    __table_args__ = (
        UniqueConstraint("company_domain", "identity_key"),
        Index("ix_contact_candidates_company", "company_domain", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("company_candidates.id"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    source_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    evaluations: Mapped[list[ContactEvaluationRow]] = relationship(back_populates="candidate")


class ContactEvaluationRow(Base):
    __tablename__ = "contact_evaluations"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id", "role_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("contact_discovery_runs.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("contact_candidates.id"), nullable=False, index=True
    )
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    current_company_match: Mapped[str] = mapped_column(String(16), nullable=False)
    role_match: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_clear: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[ContactDiscoveryRunRow] = relationship(back_populates="evaluations")
    candidate: Mapped[ContactCandidateRow] = relationship(back_populates="evaluations")


class ContactEnrichmentRunRow(Base):
    __tablename__ = "contact_enrichment_runs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    contact_discovery_run_id: Mapped[str] = mapped_column(
        ForeignKey("contact_discovery_runs.id"), nullable=False, index=True
    )
    options_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_paths: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[ContactEnrichmentItemRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ContactEnrichmentItemRow.id"
    )


class ContactEnrichmentItemRow(Base):
    __tablename__ = "contact_enrichment_items"
    __table_args__ = (UniqueConstraint("run_id", "candidate_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("contact_enrichment_runs.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("contact_candidates.id"), nullable=False, index=True
    )
    discovery_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    channels_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    review_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trace_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    run: Mapped[ContactEnrichmentRunRow] = relationship(back_populates="items")


class ContactEnrichmentFactRow(Base):
    __tablename__ = "contact_enrichment_facts"
    __table_args__ = (
        Index("ix_contact_enrichment_fact_latest", "candidate_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("contact_candidates.id"), nullable=False, index=True
    )
    enrichment_run_id: Mapped[str] = mapped_column(
        ForeignKey("contact_enrichment_runs.id"), nullable=False, index=True
    )
    channels_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    review_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
