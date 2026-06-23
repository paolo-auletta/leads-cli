from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from company_discovery.db.models import (
    ContactCandidateRow,
    ContactDiscoveryQueryRow,
    ContactDiscoveryRunRow,
    ContactEvaluationRow,
    EnrichmentRunRow,
)
from company_discovery.db.session import Database
from company_discovery.domain.contact_models import (
    ContactCandidate,
    ContactDiscoveryItem,
    ContactDiscoverySummary,
    ContactVerdict,
    EvidenceVerdict,
)
from company_discovery.domain.contact_spec import ContactSearchSpec
from company_discovery.domain.models import ExaSearchResult


class ContactRunNotFoundError(LookupError):
    pass


class ContactNotFoundError(LookupError):
    pass


class ContactDiscoveryRepository:
    RUN_ID_PREFIX = "contact-discover-"
    CREATE_RUN_ATTEMPTS = 5

    def __init__(self, database: Database) -> None:
        self.database = database

    def source_companies(self, spec: ContactSearchSpec) -> list[dict[str, Any]]:
        source = spec.company_source
        with self.database.session() as session:
            run = session.get(EnrichmentRunRow, source.enrichment_run_id)
            if run is None:
                raise ContactRunNotFoundError(
                    f"company enrichment run not found: {source.enrichment_run_id}"
                )
            if run.status != "completed":
                raise ValueError(
                    f"company enrichment run {source.enrichment_run_id} is {run.status}, not completed"
                )

            allowed = {
                "ready": {"enriched_ready"},
                "review": {"enriched_with_gaps", "independence_unconfirmed"},
                "all": {
                    "enriched_ready",
                    "enriched_with_gaps",
                    "independence_unconfirmed",
                },
            }[source.bucket]
            selected_domains = set(source.domains)
            companies: list[dict[str, Any]] = []
            for item in run.items:
                domain = item.discovery_snapshot["domain"]
                if item.outcome not in allowed:
                    continue
                if selected_domains and domain not in selected_domains:
                    continue
                companies.append(
                    {
                        "company_id": item.candidate_id,
                        "company_name": item.discovery_snapshot["company_name"],
                        "company_domain": domain,
                        "vertical": item.discovery_snapshot.get("target_vertical")
                        or item.discovery_snapshot.get("vertical"),
                        "state": item.discovery_snapshot.get("state"),
                        "linkedin_url": (item.enrichment_payload.get("linkedin") or {}).get("url"),
                        "company_enrichment_outcome": item.outcome,
                    }
                )

            if selected_domains:
                found = {company["company_domain"] for company in companies}
                missing = sorted(selected_domains - found)
                if missing:
                    raise ValueError(
                        "requested domains are not available in the selected company bucket: "
                        + ", ".join(missing)
                    )
            return companies[: spec.company_limit]

    def create_run(self, spec: ContactSearchSpec, source_spec_path: Path | None) -> str:
        for _ in range(self.CREATE_RUN_ATTEMPTS):
            try:
                with self.database.session() as session:
                    run_id = self._new_run_id()
                    session.add(
                        ContactDiscoveryRunRow(
                            id=run_id,
                            enrichment_run_id=spec.company_source.enrichment_run_id,
                            spec_payload=spec.model_dump(mode="json"),
                            source_spec_path=str(source_spec_path.resolve())
                            if source_spec_path
                            else None,
                        )
                    )
                return run_id
            except IntegrityError:
                continue
        raise RuntimeError("unable to allocate a unique contact discovery run id")

    def fresh_contacts(
        self,
        company_domain: str,
        role_key: str,
        freshness_days: int,
        limit: int,
    ) -> list[ContactDiscoveryItem]:
        cutoff = datetime.now(UTC) - timedelta(days=freshness_days)
        with self.database.session() as session:
            rows = session.execute(
                select(ContactEvaluationRow, ContactCandidateRow)
                .join(ContactCandidateRow)
                .where(
                    ContactCandidateRow.company_domain == company_domain,
                    ContactEvaluationRow.role_key == role_key,
                    ContactEvaluationRow.verdict == ContactVerdict.ACCEPTED.value,
                    ContactEvaluationRow.created_at >= cutoff,
                )
                .order_by(ContactEvaluationRow.created_at.desc())
            ).all()
            found: list[ContactDiscoveryItem] = []
            seen: set[int] = set()
            for evaluation, candidate in rows:
                if candidate.id in seen:
                    continue
                seen.add(candidate.id)
                found.append(self._item(evaluation, candidate, source="memory"))
                if len(found) == limit:
                    break
            return found

    def add_query(
        self,
        run_id: str,
        company_domain: str,
        role_key: str,
        query: str,
        results: list[ExaSearchResult],
        cost_dollars: float,
    ) -> None:
        with self.database.session() as session:
            self._require_run(session, run_id)
            session.add(
                ContactDiscoveryQueryRow(
                    run_id=run_id,
                    company_domain=company_domain,
                    role_key=role_key,
                    query_text=query,
                    result_count=len(results),
                    cost_dollars=cost_dollars,
                    raw_results=[result.model_dump(mode="json") for result in results],
                )
            )

    def upsert_candidate(self, candidate: ContactCandidate) -> int:
        with self.database.session() as session:
            row = session.scalar(
                select(ContactCandidateRow).where(
                    ContactCandidateRow.company_domain == candidate.company_domain,
                    ContactCandidateRow.identity_key == candidate.identity_key,
                )
            )
            if row is None and candidate.linkedin_url:
                row = session.scalar(
                    select(ContactCandidateRow).where(
                        ContactCandidateRow.company_domain == candidate.company_domain,
                        ContactCandidateRow.normalized_name == candidate.normalized_name,
                        ContactCandidateRow.linkedin_url.is_(None),
                    )
                )
            if row is None:
                row = ContactCandidateRow(
                    company_candidate_id=candidate.company_id,
                    company_name=candidate.company_name,
                    company_domain=candidate.company_domain,
                    full_name=candidate.full_name,
                    normalized_name=candidate.normalized_name,
                    identity_key=candidate.identity_key,
                    title=candidate.title,
                    linkedin_url=candidate.linkedin_url,
                    source_urls=candidate.source_urls,
                    evidence=candidate.evidence,
                    first_seen_at=candidate.first_seen_at,
                    last_seen_at=candidate.last_seen_at,
                )
                session.add(row)
                session.flush()
            else:
                row.company_name = candidate.company_name
                row.full_name = candidate.full_name
                row.identity_key = candidate.identity_key
                row.title = candidate.title
                row.linkedin_url = candidate.linkedin_url or row.linkedin_url
                row.source_urls = list(dict.fromkeys([*row.source_urls, *candidate.source_urls]))
                row.evidence = list(dict.fromkeys([*row.evidence, *candidate.evidence]))
                row.last_seen_at = datetime.now(UTC)
            return row.id

    def record_item(self, run_id: str, item: ContactDiscoveryItem) -> None:
        with self.database.session() as session:
            self._require_run(session, run_id)
            session.add(
                ContactEvaluationRow(
                    run_id=run_id,
                    candidate_id=item.candidate_id,
                    role_key=item.role_key,
                    verdict=item.verdict.value,
                    reason=item.reason,
                    current_company_match=item.current_company_match.value,
                    role_match=item.role_match.value,
                    identity_clear=item.identity_clear,
                    source=item.source,
                )
            )

    def complete_run(
        self, run_id: str, summary: ContactDiscoverySummary, paths: dict[str, str]
    ) -> None:
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
            row = session.execute(
                select(ContactDiscoveryRunRow)
                .options(
                    joinedload(ContactDiscoveryRunRow.queries),
                    joinedload(ContactDiscoveryRunRow.evaluations).joinedload(
                        ContactEvaluationRow.candidate
                    ),
                )
                .where(ContactDiscoveryRunRow.id == run_id)
            ).unique().scalar_one_or_none()
            if row is None:
                raise ContactRunNotFoundError(f"contact discovery run not found: {run_id}")
            enrichment_run = session.get(EnrichmentRunRow, row.enrichment_run_id)
            if enrichment_run is None:
                raise ContactRunNotFoundError(
                    "source company enrichment run not found for contact discovery run "
                    f"{run_id}: {row.enrichment_run_id}"
                )
            return {
                "run_id": row.id,
                "source_enrichment_run_id": row.enrichment_run_id,
                "source_discovery_run_id": enrichment_run.discovery_run_id,
                "spec": row.spec_payload,
                "source_spec_path": row.source_spec_path,
                "status": row.status,
                "summary": row.summary_payload,
                "artifacts": row.artifact_paths,
                "error": row.error_message,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "queries": [
                    {
                        "company_domain": query.company_domain,
                        "role_key": query.role_key,
                        "query": query.query_text,
                        "result_count": query.result_count,
                        "cost_dollars": query.cost_dollars,
                        "raw_results": query.raw_results,
                    }
                    for query in row.queries
                ],
                "items": [
                    self._item(evaluation, evaluation.candidate).model_dump(mode="json")
                    for evaluation in row.evaluations
                ],
            }

    def inspect_contact(self, run_id: str, person: str) -> list[dict[str, Any]]:
        normalized = normalize_person_name(person)
        payload = self.get_run(run_id)
        matches = [
            item
            for item in payload["items"]
            if item["candidate"]["normalized_name"] == normalized
        ]
        if not matches:
            raise ContactNotFoundError(f"person {person!r} was not found in run {run_id}")
        return matches

    @staticmethod
    def _item(
        evaluation: ContactEvaluationRow,
        candidate: ContactCandidateRow,
        source: str | None = None,
    ) -> ContactDiscoveryItem:
        return ContactDiscoveryItem(
            candidate_id=candidate.id,
            candidate=ContactCandidate(
                company_id=candidate.company_candidate_id,
                company_name=candidate.company_name,
                company_domain=candidate.company_domain,
                full_name=candidate.full_name,
                normalized_name=candidate.normalized_name,
                identity_key=candidate.identity_key,
                title=candidate.title,
                linkedin_url=candidate.linkedin_url,
                source_urls=candidate.source_urls,
                evidence=candidate.evidence,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
            ),
            role_key=evaluation.role_key,
            verdict=ContactVerdict(evaluation.verdict),
            reason=evaluation.reason,
            current_company_match=EvidenceVerdict(evaluation.current_company_match),
            role_match=EvidenceVerdict(evaluation.role_match),
            identity_clear=evaluation.identity_clear,
            source=source or evaluation.source,
        )

    @staticmethod
    def _require_run(session: Any, run_id: str) -> ContactDiscoveryRunRow:
        row = session.get(ContactDiscoveryRunRow, run_id)
        if row is None:
            raise ContactRunNotFoundError(f"contact discovery run not found: {run_id}")
        return row

    @classmethod
    def _new_run_id(cls) -> str:
        return f"{cls.RUN_ID_PREFIX}{uuid4().hex[:12]}"


def normalize_person_name(value: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())


def contact_identity_key(normalized_name: str, linkedin_url: str | None) -> str:
    if linkedin_url:
        return f"linkedin:{linkedin_url.lower().split('?', 1)[0].rstrip('/')}"
    return f"name:{normalized_name}"
