from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from company_discovery.db.models import (
    ContactCandidateRow,
    ContactDiscoveryRunRow,
    ContactEnrichmentFactRow,
    ContactEnrichmentItemRow,
    ContactEnrichmentRunRow,
    ContactEvaluationRow,
    EnrichmentRunRow,
)
from company_discovery.db.session import Database
from company_discovery.domain.contact_models import (
    ContactChannelProfile,
    ContactEnrichmentItem,
    ContactEnrichmentOutcome,
    ContactEnrichmentSummary,
)


class ContactEnrichmentRunNotFoundError(LookupError):
    pass


class ContactEnrichmentRepository:
    RUN_ID_PREFIX = "contact-enrich-"
    CREATE_RUN_ATTEMPTS = 5

    def __init__(self, database: Database) -> None:
        self.database = database

    def accepted_contacts(self, contact_run_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            run = session.get(ContactDiscoveryRunRow, contact_run_id)
            if run is None:
                raise ContactEnrichmentRunNotFoundError(
                    f"contact discovery run not found: {contact_run_id}"
                )
            if run.status != "completed":
                raise ValueError(f"contact discovery run {contact_run_id} is {run.status}, not completed")
            rows = session.execute(
                select(ContactEvaluationRow, ContactCandidateRow)
                .join(ContactCandidateRow)
                .where(
                    ContactEvaluationRow.run_id == contact_run_id,
                    ContactEvaluationRow.verdict == "accepted",
                )
                .order_by(ContactEvaluationRow.id)
            ).all()
            contacts: list[dict[str, Any]] = []
            seen: set[int] = set()
            for evaluation, candidate in rows:
                if candidate.id in seen:
                    continue
                seen.add(candidate.id)
                roles = [
                    row.role_key
                    for row in session.scalars(
                        select(ContactEvaluationRow).where(
                            ContactEvaluationRow.run_id == contact_run_id,
                            ContactEvaluationRow.candidate_id == candidate.id,
                            ContactEvaluationRow.verdict == "accepted",
                        )
                    ).all()
                ]
                contacts.append(
                    {
                        "candidate_id": candidate.id,
                        "company_name": candidate.company_name,
                        "company_domain": candidate.company_domain,
                        "full_name": candidate.full_name,
                        "normalized_name": candidate.normalized_name,
                        "title": candidate.title,
                        "linkedin_url": candidate.linkedin_url,
                        "role_keys": list(dict.fromkeys(roles)),
                        "discovery_reason": evaluation.reason,
                        "source_urls": candidate.source_urls,
                    }
                )
            return contacts

    def create_run(self, contact_run_id: str, options: dict[str, Any]) -> str:
        for _ in range(self.CREATE_RUN_ATTEMPTS):
            try:
                with self.database.session() as session:
                    if session.get(ContactDiscoveryRunRow, contact_run_id) is None:
                        raise ContactEnrichmentRunNotFoundError(
                            f"contact discovery run not found: {contact_run_id}"
                        )
                    run_id = self._new_run_id()
                    session.add(
                        ContactEnrichmentRunRow(
                            id=run_id,
                            contact_discovery_run_id=contact_run_id,
                            options_payload=options,
                        )
                    )
                return run_id
            except IntegrityError:
                continue
        raise RuntimeError("unable to allocate a unique contact enrichment run id")

    def fresh_item(self, candidate_id: int, freshness_days: int) -> ContactEnrichmentItem | None:
        cutoff = datetime.now(UTC) - timedelta(days=freshness_days)
        with self.database.session() as session:
            fact = session.scalar(
                select(ContactEnrichmentFactRow)
                .where(
                    ContactEnrichmentFactRow.candidate_id == candidate_id,
                    ContactEnrichmentFactRow.observed_at >= cutoff,
                )
                .order_by(ContactEnrichmentFactRow.observed_at.desc())
                .limit(1)
            )
            if fact is None:
                return None
            candidate = session.get(ContactCandidateRow, candidate_id)
            if candidate is None:
                return None
            discovery = {
                "company_name": candidate.company_name,
                "company_domain": candidate.company_domain,
                "contact_name": candidate.full_name,
                "title": candidate.title,
                "linkedin_url": candidate.linkedin_url,
                "role_keys": [],
                "source_urls": candidate.source_urls,
            }
            return ContactEnrichmentItem(
                candidate_id=candidate_id,
                discovery=discovery,
                channels=ContactChannelProfile.model_validate(fact.channels_payload),
                outcome=ContactEnrichmentOutcome(fact.outcome),
                review_flags=fact.review_flags,
                trace=[{"stage": "memory", "fact_id": fact.id}],
            )

    def save_item(self, run_id: str, item: ContactEnrichmentItem) -> None:
        with self.database.session() as session:
            self._require_run(session, run_id)
            session.add(
                ContactEnrichmentItemRow(
                    run_id=run_id,
                    candidate_id=item.candidate_id,
                    discovery_snapshot=item.discovery,
                    channels_payload=item.channels.model_dump(mode="json"),
                    outcome=item.outcome.value,
                    review_flags=item.review_flags,
                    trace_payload=item.trace,
                )
            )
            session.add(
                ContactEnrichmentFactRow(
                    candidate_id=item.candidate_id,
                    enrichment_run_id=run_id,
                    channels_payload=item.channels.model_dump(mode="json"),
                    outcome=item.outcome.value,
                    review_flags=item.review_flags,
                    observed_at=item.channels.observed_at,
                )
            )

    def complete_run(
        self, run_id: str, summary: ContactEnrichmentSummary, paths: dict[str, str]
    ) -> None:
        with self.database.session() as session:
            run = self._require_run(session, run_id)
            run.status = "completed"
            run.summary_payload = summary.model_dump(mode="json")
            run.artifact_paths = paths
            run.completed_at = datetime.now(UTC)

    def fail_run(self, run_id: str, error: Exception) -> None:
        with self.database.session() as session:
            run = self._require_run(session, run_id)
            run.status = "failed"
            run.error_message = str(error)
            run.completed_at = datetime.now(UTC)

    def set_artifacts(self, run_id: str, paths: dict[str, str]) -> None:
        with self.database.session() as session:
            self._require_run(session, run_id).artifact_paths = paths

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            row = session.scalar(
                select(ContactEnrichmentRunRow)
                .options(joinedload(ContactEnrichmentRunRow.items))
                .where(ContactEnrichmentRunRow.id == run_id)
            )
            if row is None:
                raise ContactEnrichmentRunNotFoundError(
                    f"contact enrichment run not found: {run_id}"
                )
            contact_run = session.get(ContactDiscoveryRunRow, row.contact_discovery_run_id)
            if contact_run is None:
                raise ContactEnrichmentRunNotFoundError(
                    f"source contact discovery run missing: {row.contact_discovery_run_id}"
                )
            company_run = session.get(EnrichmentRunRow, contact_run.enrichment_run_id)
            if company_run is None:
                raise ContactEnrichmentRunNotFoundError(
                    f"source company enrichment run missing: {contact_run.enrichment_run_id}"
                )
            return {
                "run_id": row.id,
                "source_contact_run_id": row.contact_discovery_run_id,
                "source_enrichment_run_id": contact_run.enrichment_run_id,
                "source_discovery_run_id": company_run.discovery_run_id,
                "options": row.options_payload,
                "status": row.status,
                "summary": row.summary_payload,
                "artifacts": row.artifact_paths,
                "error": row.error_message,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "items": [
                    {
                        "candidate_id": item.candidate_id,
                        "discovery": item.discovery_snapshot,
                        "channels": item.channels_payload,
                        "outcome": item.outcome,
                        "review_flags": item.review_flags,
                        "trace": item.trace_payload,
                    }
                    for item in row.items
                ],
            }

    def inspect_contact(self, run_id: str, person: str) -> list[dict[str, Any]]:
        normalized = " ".join(
            "".join(char.lower() if char.isalnum() else " " for char in person).split()
        )
        matches = [
            item
            for item in self.get_run(run_id)["items"]
            if " ".join(
                "".join(
                    char.lower() if char.isalnum() else " "
                    for char in item["discovery"]["contact_name"]
                ).split()
            )
            == normalized
        ]
        if not matches:
            raise LookupError(f"person {person!r} was not found in run {run_id}")
        return matches

    @staticmethod
    def _require_run(session: Any, run_id: str) -> ContactEnrichmentRunRow:
        row = session.get(ContactEnrichmentRunRow, run_id)
        if row is None:
            raise ContactEnrichmentRunNotFoundError(
                f"contact enrichment run not found: {run_id}"
            )
        return row

    @classmethod
    def _new_run_id(cls) -> str:
        return f"{cls.RUN_ID_PREFIX}{uuid4().hex[:12]}"
