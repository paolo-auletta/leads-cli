from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from company_discovery.db.models import (
    CandidateEvaluationRow,
    CompanyCandidateRow,
    DiscoveryQueryRow,
    DiscoveryRunRow,
    RawResultRow,
)
from company_discovery.db.session import Database
from company_discovery.domain.models import (
    CandidateBucket,
    CandidateEvaluation,
    ExaSearchResult,
    NormalizedCandidate,
    RunSummary,
)
from company_discovery.domain.spec import CompanySearchSpec


@dataclass(frozen=True)
class MemoryRecord:
    candidate_id: int
    candidate: NormalizedCandidate
    latest_fit: str | None
    latest_bucket: str | None
    latest_reason: str | None
    latest_reason_codes: tuple[str, ...]
    latest_evaluation: CandidateEvaluation | None
    ever_selected: bool
    latest_spec: CompanySearchSpec | None = None


class RunNotFoundError(LookupError):
    pass


class CandidateNotFoundError(LookupError):
    pass


class DiscoveryRepository:
    RUN_ID_PREFIX = "company-discover-"
    CREATE_RUN_ATTEMPTS = 5

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_run(self, spec: CompanySearchSpec, source_spec_path: str | None = None) -> str:
        for _ in range(self.CREATE_RUN_ATTEMPTS):
            try:
                run_id = self._new_run_id()
                with self.database.session() as session:
                    session.add(
                        DiscoveryRunRow(
                            id=run_id,
                            spec_payload=spec.model_dump(mode="json"),
                            source_spec_path=source_spec_path,
                            status="running",
                        )
                    )
                return run_id
            except IntegrityError:
                continue
        raise RuntimeError("unable to allocate a unique company discovery run id")

    @classmethod
    def _new_run_id(cls) -> str:
        return f"{cls.RUN_ID_PREFIX}{uuid4().hex[:12]}"

    def complete_run(
        self,
        run_id: str,
        summary: RunSummary,
        artifact_paths: dict[str, str],
    ) -> None:
        with self.database.session() as session:
            row = self._require_run(session, run_id)
            row.status = "completed"
            row.summary_payload = summary.model_dump(mode="json")
            row.artifact_paths = artifact_paths
            row.completed_at = datetime.now(UTC)

    def fail_run(self, run_id: str, error: Exception) -> None:
        with self.database.session() as session:
            row = self._require_run(session, run_id)
            row.status = "failed"
            row.error_message = str(error)
            row.completed_at = datetime.now(UTC)

    def set_artifacts(self, run_id: str, artifact_paths: dict[str, str]) -> None:
        with self.database.session() as session:
            row = self._require_run(session, run_id)
            row.artifact_paths = artifact_paths

    def add_query(self, run_id: str, order: int, text: str, rationale: str = "") -> int:
        with self.database.session() as session:
            row = DiscoveryQueryRow(
                run_id=run_id,
                query_order=order,
                query_text=text,
                rationale=rationale,
            )
            session.add(row)
            session.flush()
            return row.id

    def save_query_results(
        self,
        run_id: str,
        query_id: int,
        results: list[ExaSearchResult],
        cost_dollars: float,
    ) -> None:
        with self.database.session() as session:
            query = session.get(DiscoveryQueryRow, query_id)
            if query is None or query.run_id != run_id:
                raise LookupError(f"query {query_id} does not belong to run {run_id}")
            query.result_count = len(results)
            query.cost_dollars = cost_dollars
            session.add_all(
                RawResultRow(
                    run_id=run_id,
                    query_id=query_id,
                    result_position=result.position,
                    observed_url=result.url,
                    observed_title=result.title,
                    raw_payload=result.model_dump(mode="json"),
                )
                for result in results
            )

    def upsert_candidate(self, candidate: NormalizedCandidate) -> int:
        with self.database.session() as session:
            row = session.scalar(
                select(CompanyCandidateRow).where(CompanyCandidateRow.domain == candidate.domain)
            )
            payload = candidate.model_dump(mode="json")
            if row is None:
                row = CompanyCandidateRow(
                    canonical_name=candidate.company_name,
                    domain=candidate.domain,
                    dedupe_key=candidate.dedupe_key,
                    normalized_payload=payload,
                    vertical=candidate.vertical,
                    country=candidate.country,
                    state=candidate.state,
                    employee_min=candidate.employee_min,
                    employee_max=candidate.employee_max,
                    ownership_type=candidate.ownership_type,
                    excluded=candidate.excluded,
                    first_seen_at=candidate.first_seen_at,
                    last_seen_at=candidate.last_seen_at,
                )
                session.add(row)
                session.flush()
            else:
                merged = self._merge_candidate_payload(row.normalized_payload, payload)
                row.canonical_name = candidate.company_name or row.canonical_name
                row.normalized_payload = merged
                row.last_seen_at = candidate.last_seen_at
                row.excluded = row.excluded or candidate.excluded
            return row.id

    def record_evaluation(
        self,
        run_id: str,
        candidate_id: int,
        evaluation: CandidateEvaluation,
        bucket: CandidateBucket,
        source: str,
    ) -> None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            candidate = session.get(CompanyCandidateRow, candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"candidate not found: {candidate_id}")
            existing = session.scalar(
                select(CandidateEvaluationRow).where(
                    CandidateEvaluationRow.run_id == run_id,
                    CandidateEvaluationRow.candidate_id == candidate_id,
                )
            )
            if existing is not None:
                raise ValueError(f"candidate {candidate.domain} already evaluated in run {run_id}")
            session.add(
                CandidateEvaluationRow(
                    run_id=run_id,
                    candidate_id=candidate_id,
                    evaluation_payload=evaluation.model_dump(mode="json"),
                    fit_outcome=evaluation.fit.value,
                    bucket=bucket.value,
                    reason=evaluation.reason,
                    reason_codes=evaluation.reason_codes,
                    source=source,
                    created_at=now,
                )
            )
            self._apply_inferences(candidate, evaluation)
            candidate.prior_bucket = bucket.value
            candidate.prior_reason = evaluation.reason
            candidate.last_evaluated_at = now

    def memory_records(self) -> list[MemoryRecord]:
        latest = (
            select(
                CandidateEvaluationRow.candidate_id,
                func.max(CandidateEvaluationRow.id).label("latest_id"),
            )
            .group_by(CandidateEvaluationRow.candidate_id)
            .subquery()
        )
        latest_evaluations: Select[tuple[CompanyCandidateRow, CandidateEvaluationRow | None]] = (
            select(CompanyCandidateRow, CandidateEvaluationRow)
            .outerjoin(latest, latest.c.candidate_id == CompanyCandidateRow.id)
            .outerjoin(
                CandidateEvaluationRow,
                CandidateEvaluationRow.id == latest.c.latest_id,
            )
            .order_by(CompanyCandidateRow.last_seen_at.desc())
        )
        with self.database.session() as session:
            rows = session.execute(latest_evaluations).all()
            selected_ids = set(
                session.scalars(
                    select(CandidateEvaluationRow.candidate_id).where(
                        CandidateEvaluationRow.bucket == CandidateBucket.SELECTED.value
                    )
                ).all()
            )
            run_specs = {
                row.id: CompanySearchSpec.model_validate(row.spec_payload)
                for row in session.scalars(select(DiscoveryRunRow)).all()
            }
            return [
                MemoryRecord(
                    candidate_id=candidate_row.id,
                    candidate=NormalizedCandidate.model_validate(candidate_row.normalized_payload),
                    latest_fit=evaluation.fit_outcome if evaluation else None,
                    latest_bucket=evaluation.bucket if evaluation else None,
                    latest_reason=evaluation.reason if evaluation else None,
                    latest_reason_codes=tuple(evaluation.reason_codes) if evaluation else (),
                    latest_evaluation=(
                        CandidateEvaluation.model_validate(evaluation.evaluation_payload)
                        if evaluation
                        else None
                    ),
                    ever_selected=candidate_row.id in selected_ids,
                    latest_spec=run_specs.get(evaluation.run_id) if evaluation else None,
                )
                for candidate_row, evaluation in rows
            ]

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.scalar(
                select(DiscoveryRunRow)
                .options(joinedload(DiscoveryRunRow.queries))
                .where(DiscoveryRunRow.id == run_id)
            )
            if row is None:
                raise RunNotFoundError(f"run not found: {run_id}")
            evaluations = session.execute(
                select(CandidateEvaluationRow, CompanyCandidateRow)
                .join(CompanyCandidateRow)
                .where(CandidateEvaluationRow.run_id == run_id)
                .order_by(CandidateEvaluationRow.id)
            ).all()
            return {
                "run_id": row.id,
                "status": row.status,
                "spec": row.spec_payload,
                "summary": row.summary_payload,
                "artifacts": row.artifact_paths,
                "error": row.error_message,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "queries": [query.query_text for query in row.queries],
                "candidates": [
                    {
                        "candidate_id": candidate.id,
                        "company": candidate.normalized_payload,
                        "evaluation": evaluation.evaluation_payload,
                        "bucket": evaluation.bucket,
                        "source": evaluation.source,
                    }
                    for evaluation, candidate in evaluations
                ],
            }

    def inspect_candidate(self, run_id: str, domain: str) -> dict[str, Any]:
        with self.database.session() as session:
            result = session.execute(
                select(CandidateEvaluationRow, CompanyCandidateRow)
                .join(CompanyCandidateRow)
                .where(
                    CandidateEvaluationRow.run_id == run_id,
                    CompanyCandidateRow.domain == domain,
                )
            ).first()
            if result is None:
                raise CandidateNotFoundError(f"domain {domain} was not evaluated in run {run_id}")
            evaluation, candidate = result
            raw_hits = session.scalars(
                select(RawResultRow).where(
                    RawResultRow.run_id == run_id,
                    RawResultRow.observed_url.contains(domain),
                )
            ).all()
            return {
                "company": candidate.normalized_payload,
                "evaluation": evaluation.evaluation_payload,
                "bucket": evaluation.bucket,
                "source": evaluation.source,
                "raw_hits": [hit.raw_payload for hit in raw_hits],
            }

    @staticmethod
    def _require_run(session: Any, run_id: str) -> DiscoveryRunRow:
        row = session.get(DiscoveryRunRow, run_id)
        if row is None:
            raise RunNotFoundError(f"run not found: {run_id}")
        return row

    @staticmethod
    def _merge_candidate_payload(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        for key, value in incoming.items():
            if key == "sightings":
                existing = {item["url"]: item for item in merged.get("sightings", [])}
                existing.update({item["url"]: item for item in value})
                merged[key] = list(existing.values())
            elif value is not None and value != []:
                merged[key] = value
        return merged

    @staticmethod
    def _apply_inferences(candidate: CompanyCandidateRow, evaluation: CandidateEvaluation) -> None:
        updates = {
            "vertical": evaluation.inferred_vertical,
            "country": evaluation.inferred_country,
            "state": evaluation.inferred_state,
            "employee_min": evaluation.inferred_employee_min,
            "employee_max": evaluation.inferred_employee_max,
            "ownership_type": evaluation.inferred_ownership_type,
        }
        payload = dict(candidate.normalized_payload)
        for field, value in updates.items():
            if value is not None:
                setattr(candidate, field, value)
                payload[field] = value
        candidate.excluded = evaluation.excluded.value == "yes"
        payload["excluded"] = candidate.excluded
        candidate.normalized_payload = payload
