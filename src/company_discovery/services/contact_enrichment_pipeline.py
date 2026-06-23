from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from company_discovery.adapters.protocols import ContactEnrichmentProvider
from company_discovery.db.contact_enrichment_repository import ContactEnrichmentRepository
from company_discovery.domain.contact_models import (
    ApolloBatchResult,
    ApolloPersonMatch,
    ApolloPersonRequest,
    ContactChannelProfile,
    ContactEnrichmentItem,
    ContactEnrichmentOutcome,
    ContactEnrichmentResult,
    ContactEnrichmentSummary,
)
from company_discovery.reports.contact_enrichment_exporter import (
    ContactEnrichmentArtifactExporter,
)
from company_discovery.services.contact_enrichment_progress import (
    ContactEnrichmentProgressReporter,
    NullContactEnrichmentProgressReporter,
)
from company_discovery.services.normalization import canonical_domain


PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "aol.com", "proton.me", "protonmail.com",
}
INVALID_EMAIL_STATUSES = {"invalid", "bounced", "unavailable", "do_not_mail"}


@dataclass(frozen=True)
class ContactEnrichmentOptions:
    reveal_email: bool = True
    reveal_phone: bool = True
    refresh: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "reveal_email": self.reveal_email,
            "reveal_phone": self.reveal_phone,
            "refresh": self.refresh,
        }


class ContactEnrichmentPipeline:
    BATCH_SIZE = 10

    def __init__(
        self,
        *,
        repository: ContactEnrichmentRepository,
        exporter: ContactEnrichmentArtifactExporter,
        provider: ContactEnrichmentProvider,
        freshness_days: int = 14,
        poll_interval_seconds: float = 2,
        poll_timeout_seconds: float = 120,
    ) -> None:
        self._repository = repository
        self._exporter = exporter
        self._provider = provider
        self._freshness_days = freshness_days
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds

    def enrich(
        self,
        contact_run_id: str,
        *,
        options: ContactEnrichmentOptions | None = None,
        progress: ContactEnrichmentProgressReporter | None = None,
    ) -> ContactEnrichmentResult:
        selected_options = options or ContactEnrichmentOptions()
        reporter = progress or NullContactEnrichmentProgressReporter()
        contacts = self._repository.accepted_contacts(contact_run_id)
        run_id = self._repository.create_run(contact_run_id, selected_options.as_dict())
        try:
            return self._run(
                run_id, contact_run_id, contacts, selected_options, reporter
            )
        except Exception as exc:
            self._repository.fail_run(run_id, exc)
            raise

    def _run(
        self,
        run_id: str,
        contact_run_id: str,
        contacts: list[dict[str, object]],
        options: ContactEnrichmentOptions,
        reporter: ContactEnrichmentProgressReporter,
    ) -> ContactEnrichmentResult:
        summary = ContactEnrichmentSummary(contacts_loaded=len(contacts))
        items: list[ContactEnrichmentItem] = []
        pending: list[dict[str, object]] = []
        reporter.start(contact_run_id, len(contacts))

        for contact in contacts:
            remembered = None
            if not options.refresh:
                remembered = self._repository.fresh_item(
                    int(contact["candidate_id"]), self._freshness_days
                )
            if remembered is not None and self._memory_satisfies(remembered, options):
                channels = remembered.channels.model_copy(
                    update={
                        "email": remembered.channels.email if options.reveal_email else None,
                        "email_status": (
                            remembered.channels.email_status if options.reveal_email else None
                        ),
                        "phone": remembered.channels.phone if options.reveal_phone else None,
                    }
                )
                item = remembered.model_copy(
                    update={"discovery": self._discovery(contact), "channels": channels}
                )
                items.append(item)
                summary.memory_reused += 1
            else:
                pending.append(contact)
        reporter.memory(summary.memory_reused, len(pending))

        batches = [pending[index : index + self.BATCH_SIZE] for index in range(0, len(pending), self.BATCH_SIZE)]
        for batch_index, batch in enumerate(batches, start=1):
            reporter.batch(batch_index, len(batches), len(batch))
            requests = [self._request(contact) for contact in batch]
            summary.apollo_batches += 1
            summary.apollo_requests += len(requests)
            result = self._provider.enrich_people(
                requests,
                reveal_email=options.reveal_email,
                reveal_phone=options.reveal_phone,
            )
            if result.pending:
                if not result.request_id:
                    raise RuntimeError("Apollo returned a pending result without a request_id")
                result, polls = self._wait_for_result(result.request_id, reporter)
                summary.async_polls += polls
            by_id = {match.candidate_id: match for match in result.matches}
            for contact in batch:
                candidate_id = int(contact["candidate_id"])
                match = by_id.get(candidate_id) or ApolloPersonMatch(
                    candidate_id=candidate_id, person_found=False
                )
                item = self._resolve(contact, match, options)
                items.append(item)
                reporter.outcome(
                    str(contact["full_name"]), item.outcome.value, item.review_flags
                )

        for item in items:
            self._repository.save_item(run_id, item)
            if item.outcome == ContactEnrichmentOutcome.READY:
                summary.ready += 1
            elif item.outcome == ContactEnrichmentOutcome.REVIEW:
                summary.review += 1
            else:
                summary.blocked += 1

        lineage = self._repository.get_run(run_id)
        payload = {
            "run_id": run_id,
            "source_contact_run_id": contact_run_id,
            "source_enrichment_run_id": lineage["source_enrichment_run_id"],
            "source_discovery_run_id": lineage["source_discovery_run_id"],
            "options": options.as_dict(),
            "status": "completed",
            "items": [item.model_dump(mode="json") for item in items],
        }
        paths = self._exporter.export(payload, summary)
        self._repository.complete_run(run_id, summary, paths)
        reporter.save(run_id)
        return ContactEnrichmentResult(
            run_id=run_id,
            source_contact_run_id=contact_run_id,
            summary=summary,
            items=items,
            artifact_paths=paths,
        )

    def _wait_for_result(
        self, request_id: str, reporter: ContactEnrichmentProgressReporter
    ) -> tuple[ApolloBatchResult, int]:
        deadline = time.monotonic() + self._poll_timeout_seconds
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            reporter.poll(request_id, attempts)
            result = self._provider.poll(request_id)
            if not result.pending:
                return result, attempts
            time.sleep(self._poll_interval_seconds)
        raise TimeoutError(
            f"Apollo enrichment {request_id} was still pending after "
            f"{self._poll_timeout_seconds:g} seconds"
        )

    @staticmethod
    def _request(contact: dict[str, object]) -> ApolloPersonRequest:
        parts = str(contact["full_name"]).split()
        return ApolloPersonRequest(
            candidate_id=int(contact["candidate_id"]),
            first_name=parts[0],
            last_name=" ".join(parts[1:]) if len(parts) > 1 else parts[0],
            full_name=str(contact["full_name"]),
            company_name=str(contact["company_name"]),
            company_domain=str(contact["company_domain"]),
            linkedin_url=str(contact["linkedin_url"]) if contact.get("linkedin_url") else None,
        )

    @staticmethod
    def _discovery(contact: dict[str, object]) -> dict[str, object]:
        return {
            "company_name": contact["company_name"],
            "company_domain": contact["company_domain"],
            "contact_name": contact["full_name"],
            "title": contact["title"],
            "linkedin_url": contact.get("linkedin_url"),
            "role_keys": contact.get("role_keys", []),
            "source_urls": contact.get("source_urls", []),
            "discovery_reason": contact.get("discovery_reason"),
        }

    @classmethod
    def _resolve(
        cls,
        contact: dict[str, object],
        match: ApolloPersonMatch,
        options: ContactEnrichmentOptions,
    ) -> ContactEnrichmentItem:
        discovery = cls._discovery(contact)
        flags: list[str] = []
        target_domain = str(contact["company_domain"]).lower()
        target_linkedin = cls._normalize_linkedin(contact.get("linkedin_url"))
        apollo_linkedin = cls._normalize_linkedin(match.linkedin_url)
        target_name = cls._normalize_text(str(contact["full_name"]))
        apollo_name = cls._normalize_text(match.full_name or "")

        identity_match = match.person_found
        if target_linkedin and apollo_linkedin and target_linkedin != apollo_linkedin:
            identity_match = False
            flags.append("linkedin_identity_mismatch")
        elif apollo_name and apollo_name != target_name:
            identity_match = False
            flags.append("person_name_mismatch")
        if not match.person_found:
            flags.append("no_apollo_match")

        email = match.email if options.reveal_email else None
        if email and match.email_status and match.email_status.lower() in INVALID_EMAIL_STATUSES:
            email = None
            flags.append(f"email_{match.email_status.lower()}")
        email_domain = cls._email_domain(email)
        company_match = match.organization_domain == target_domain
        company_supported = company_match or email_domain == target_domain
        if match.organization_domain and not company_match:
            flags.append("apollo_company_mismatch")
        if email_domain in PERSONAL_EMAIL_DOMAINS:
            flags.append("personal_email")
        elif email_domain and email_domain != target_domain:
            flags.append("email_domain_mismatch")

        phone = match.phones[0] if options.reveal_phone and match.phones else None
        has_channel = bool(email or phone)
        if not has_channel:
            flags.append("no_contact_channels")

        if not identity_match:
            outcome = ContactEnrichmentOutcome.BLOCKED
        elif not has_channel:
            outcome = ContactEnrichmentOutcome.BLOCKED
        elif not company_supported:
            flags.append("company_not_confirmed_by_apollo_channel")
            outcome = ContactEnrichmentOutcome.REVIEW
        elif "personal_email" in flags or "email_domain_mismatch" in flags:
            outcome = ContactEnrichmentOutcome.REVIEW
        else:
            outcome = ContactEnrichmentOutcome.READY

        channels = ContactChannelProfile(
            email_requested=options.reveal_email,
            phone_requested=options.reveal_phone,
            email=email,
            email_status=match.email_status if options.reveal_email else None,
            phone=phone,
            apollo_person_id=match.apollo_person_id,
            apollo_linkedin_url=match.linkedin_url,
            apollo_company_name=match.organization_name,
            apollo_company_domain=match.organization_domain,
            apollo_title=match.title,
        )
        trace = [
            {
                "stage": "apollo_match",
                "identity_match": identity_match,
                "company_match": company_match,
                "email_domain": email_domain,
                "company_supported": company_supported,
                "provider_record": match.raw,
            },
            {"stage": "outcome", "value": outcome.value, "flags": flags},
        ]
        return ContactEnrichmentItem(
            candidate_id=int(contact["candidate_id"]),
            discovery=discovery,
            channels=channels,
            outcome=outcome,
            review_flags=list(dict.fromkeys(flags)),
            trace=trace,
        )

    @staticmethod
    def _memory_satisfies(
        item: ContactEnrichmentItem, options: ContactEnrichmentOptions
    ) -> bool:
        if options.reveal_email and not item.channels.email_requested:
            return False
        if options.reveal_phone and not item.channels.phone_requested:
            return False
        return True

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(
            "".join(char.lower() if char.isalnum() else " " for char in value).split()
        )

    @staticmethod
    def _normalize_linkedin(value: object) -> str | None:
        if not value:
            return None
        parsed = urlsplit(str(value))
        return f"{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/').lower()}"

    @staticmethod
    def _email_domain(email: str | None) -> str | None:
        if not email or "@" not in email:
            return None
        return canonical_domain(email.rsplit("@", 1)[1])
