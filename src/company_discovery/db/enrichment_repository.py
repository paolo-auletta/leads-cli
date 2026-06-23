from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from company_discovery.db.models import (
    CandidateEvaluationRow,
    CompanyCandidateRow,
    DiscoveryRunRow,
    EnrichmentFactRow,
    EnrichmentItemRow,
    EnrichmentRunRow,
)
from company_discovery.db.repository import CandidateNotFoundError, RunNotFoundError
from company_discovery.db.session import Database
from company_discovery.domain.models import EnrichmentItem, EnrichmentProfile, EnrichmentSummary


class EnrichmentRunNotFoundError(LookupError):
    pass


class EnrichmentRepository:
    RUN_ID_PREFIX = "company-enrich-"
    CREATE_RUN_ATTEMPTS = 5

    def __init__(self, database: Database) -> None:
        self.database = database

    def discovery_candidates(self, run_id: str, bucket: str, limit: int | None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            run = session.get(DiscoveryRunRow, run_id)
            if run is None:
                raise RunNotFoundError(f"run not found: {run_id}")
            if run.status != "completed":
                raise ValueError(f"discovery run {run_id} is {run.status}, not completed")
            statement = (
                select(CandidateEvaluationRow, CompanyCandidateRow)
                .join(CompanyCandidateRow)
                .where(
                    CandidateEvaluationRow.run_id == run_id,
                    CandidateEvaluationRow.bucket == bucket,
                )
                .order_by(CandidateEvaluationRow.id)
            )
            if limit is not None:
                statement = statement.limit(limit)
            rows = session.execute(statement).all()
            return [
                {
                    "candidate_id": candidate.id,
                    "company": candidate.normalized_payload,
                    "evaluation": evaluation.evaluation_payload,
                    "bucket": evaluation.bucket,
                    "source": evaluation.source,
                    "spec": run.spec_payload,
                }
                for evaluation, candidate in rows
            ]

    def create_run(self, discovery_run_id: str, bucket: str, options: dict[str, Any]) -> str:
        for _ in range(self.CREATE_RUN_ATTEMPTS):
            try:
                with self.database.session() as session:
                    if session.get(DiscoveryRunRow, discovery_run_id) is None:
                        raise RunNotFoundError(f"run not found: {discovery_run_id}")
                    run_id = self._new_run_id()
                    session.add(
                        EnrichmentRunRow(
                            id=run_id,
                            discovery_run_id=discovery_run_id,
                            bucket=bucket,
                            options_payload=options,
                        )
                    )
                return run_id
            except IntegrityError:
                continue
        raise RuntimeError("unable to allocate a unique enrichment run id")

    def fresh_profile(self, candidate_id: int, freshness_days: int) -> EnrichmentProfile:
        cutoff = datetime.now(UTC) - timedelta(days=freshness_days)
        latest = (
            select(
                EnrichmentFactRow.fact_kind,
                func.max(EnrichmentFactRow.id).label("latest_id"),
            )
            .where(
                EnrichmentFactRow.candidate_id == candidate_id,
                EnrichmentFactRow.observed_at >= cutoff,
            )
            .group_by(EnrichmentFactRow.fact_kind)
            .subquery()
        )
        with self.database.session() as session:
            facts = session.scalars(
                select(EnrichmentFactRow).join(latest, EnrichmentFactRow.id == latest.c.latest_id)
            ).all()
        payload = {fact.fact_kind: fact.fact_payload for fact in facts}
        return EnrichmentProfile.model_validate(payload)

    def save_item(self, run_id: str, item: EnrichmentItem) -> None:
        with self.database.session() as session:
            if session.get(CompanyCandidateRow, item.company_id) is None:
                raise CandidateNotFoundError(f"candidate not found: {item.company_id}")
            session.add(
                EnrichmentItemRow(
                    run_id=run_id,
                    candidate_id=item.company_id,
                    discovery_snapshot=item.discovery,
                    enrichment_payload=item.enrichment.model_dump(mode="json"),
                    inherited_status={key: value.value for key, value in item.inherited_status.items()},
                    outcome=item.outcome.value,
                    conflicts=item.conflicts,
                    review_flags=item.review_flags,
                    trace_payload=item.trace,
                )
            )
            for kind in ("phone", "location", "independence", "linkedin"):
                fact = getattr(item.enrichment, kind)
                if fact is not None:
                    session.add(
                        EnrichmentFactRow(
                            candidate_id=item.company_id,
                            enrichment_run_id=run_id,
                            fact_kind=kind,
                            fact_payload=fact.model_dump(mode="json"),
                            observed_at=fact.observed_at,
                        )
                    )

    def complete_run(self, run_id: str, summary: EnrichmentSummary, paths: dict[str, str]) -> None:
        with self.database.session() as session:
            row = self._require_run(session, run_id)
            row.status = "completed"
            row.summary_payload = summary.model_dump(mode="json")
            row.artifact_paths = paths
            row.completed_at = datetime.now(UTC)

    def fail_run(self, run_id: str, error: Exception) -> None:
        with self.database.session() as session:
            row = self._require_run(session, run_id)
            row.status = "failed"
            row.error_message = str(error)
            row.completed_at = datetime.now(UTC)

    def set_artifacts(self, run_id: str, paths: dict[str, str]) -> None:
        with self.database.session() as session:
            self._require_run(session, run_id).artifact_paths = paths

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.scalar(
                select(EnrichmentRunRow)
                .options(joinedload(EnrichmentRunRow.items))
                .where(EnrichmentRunRow.id == run_id)
            )
            if row is None:
                raise EnrichmentRunNotFoundError(f"enrichment run not found: {run_id}")
            return {
                "run_id": row.id,
                "discovery_run_id": row.discovery_run_id,
                "bucket": row.bucket,
                "options": row.options_payload,
                "status": row.status,
                "summary": row.summary_payload,
                "artifacts": row.artifact_paths,
                "error": row.error_message,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "items": [
                    {
                        "company_id": item.candidate_id,
                        "discovery": item.discovery_snapshot,
                        "enrichment": item.enrichment_payload,
                        "inherited_status": item.inherited_status,
                        "outcome": item.outcome,
                        "conflicts": item.conflicts,
                        "review_flags": item.review_flags,
                        "trace": item.trace_payload,
                    }
                    for item in row.items
                ],
            }

    def inspect_item(self, run_id: str, domain: str) -> dict[str, Any]:
        payload = self.get_run(run_id)
        for item in payload["items"]:
            if item["discovery"]["domain"] == domain:
                return item
        raise CandidateNotFoundError(f"domain {domain} was not enriched in run {run_id}")

    @staticmethod
    def _require_run(session: Any, run_id: str) -> EnrichmentRunRow:
        row = session.get(EnrichmentRunRow, run_id)
        if row is None:
            raise EnrichmentRunNotFoundError(f"enrichment run not found: {run_id}")
        return row

    @classmethod
    def _new_run_id(cls) -> str:
        return f"{cls.RUN_ID_PREFIX}{uuid4().hex[:12]}"
