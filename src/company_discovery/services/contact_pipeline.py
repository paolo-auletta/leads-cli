from __future__ import annotations

from pathlib import Path

from company_discovery.adapters.protocols import ContactSearchProvider
from company_discovery.db.contact_repository import (
    ContactDiscoveryRepository,
    contact_identity_key,
    normalize_person_name,
)
from company_discovery.domain.contact_models import (
    ContactCandidate,
    ContactDiscoveryItem,
    ContactDiscoveryResult,
    ContactDiscoverySummary,
    ContactSearchBatch,
    ContactVerdict,
)
from company_discovery.domain.contact_spec import ContactRoleTarget, ContactSearchSpec
from company_discovery.reports.contact_exporter import ContactDiscoveryArtifactExporter
from company_discovery.services.contact_evaluator import ContactEvaluator
from company_discovery.services.contact_progress import (
    ContactProgressReporter,
    NullContactProgressReporter,
)


class ContactDiscoveryPipeline:
    def __init__(
        self,
        *,
        repository: ContactDiscoveryRepository,
        exporter: ContactDiscoveryArtifactExporter,
        search_provider: ContactSearchProvider | None,
        evaluator: ContactEvaluator | None,
        results_per_query: int = 10,
    ) -> None:
        self._repository = repository
        self._exporter = exporter
        self._search_provider = search_provider
        self._evaluator = evaluator
        self._results_per_query = results_per_query

    def discover(
        self,
        spec: ContactSearchSpec,
        *,
        source_spec_path: Path | None = None,
        progress: ContactProgressReporter | None = None,
    ) -> ContactDiscoveryResult:
        reporter = progress or NullContactProgressReporter()
        companies = self._repository.source_companies(spec)
        run_id = self._repository.create_run(spec, source_spec_path)
        try:
            return self._run(run_id, spec, companies, reporter)
        except Exception as exc:
            self._repository.fail_run(run_id, exc)
            raise

    def _run(
        self,
        run_id: str,
        spec: ContactSearchSpec,
        companies: list[dict[str, object]],
        reporter: ContactProgressReporter,
    ) -> ContactDiscoveryResult:
        summary = ContactDiscoverySummary(companies_loaded=len(companies))
        items: list[ContactDiscoveryItem] = []
        accepted_ids: set[int] = set()
        reporter.start(spec.company_source.enrichment_run_id, len(companies), len(spec.roles))

        stop = False
        for company_index, company in enumerate(companies, start=1):
            reporter.company(
                company_index,
                len(companies),
                str(company["company_name"]),
                str(company["company_domain"]),
            )
            for role in spec.roles:
                if self._limit_reached(spec, accepted_ids):
                    stop = True
                    break
                memory_limit = role.max_per_company
                if spec.contact_limit is not None:
                    memory_limit = min(
                        memory_limit,
                        spec.contact_limit - len(accepted_ids),
                    )
                memory = self._repository.fresh_contacts(
                    str(company["company_domain"]),
                    role.key,
                    spec.memory_freshness_days,
                    memory_limit,
                )
                reporter.memory(role.key, len(memory), role.max_per_company)
                for remembered in memory:
                    item = remembered.model_copy(update={"source": "memory"})
                    self._repository.record_item(run_id, item)
                    items.append(item)
                    accepted_ids.add(item.candidate_id)
                summary.memory_reused += len(memory)

                gap = role.max_per_company - len(memory)
                if gap <= 0 or self._limit_reached(spec, accepted_ids):
                    continue
                if spec.contact_limit is not None:
                    gap = min(gap, spec.contact_limit - len(accepted_ids))
                summary.role_gaps += gap
                external = self._discover_role(run_id, company, role, spec, gap, reporter)
                for item in external:
                    if any(
                        prior.candidate_id == item.candidate_id
                        and prior.role_key == item.role_key
                        for prior in items
                    ):
                        continue
                    self._repository.record_item(run_id, item)
                    items.append(item)
                    if item.verdict == ContactVerdict.ACCEPTED:
                        accepted_ids.add(item.candidate_id)
                summary.queries_run += 2
                summary.raw_results += sum(
                    int(trace["result_count"])
                    for trace in self._last_query_trace
                )
            if stop:
                break

        best_verdict = self._best_verdicts(items)
        summary.unique_people = len(best_verdict)
        summary.accepted = sum(
            verdict == ContactVerdict.ACCEPTED for verdict in best_verdict.values()
        )
        summary.review = sum(
            verdict == ContactVerdict.REVIEW for verdict in best_verdict.values()
        )
        summary.rejected = sum(
            verdict == ContactVerdict.REJECTED for verdict in best_verdict.values()
        )
        payload = self._repository.get_run(run_id)
        payload["summary"] = summary.model_dump(mode="json")
        payload["status"] = "completed"
        paths = self._exporter.export(payload, summary)
        self._repository.complete_run(run_id, summary, paths)
        reporter.save(run_id)
        return ContactDiscoveryResult(
            run_id=run_id,
            source_enrichment_run_id=spec.company_source.enrichment_run_id,
            summary=summary,
            items=items,
            artifact_paths=paths,
        )

    def _discover_role(
        self,
        run_id: str,
        company: dict[str, object],
        role: ContactRoleTarget,
        spec: ContactSearchSpec,
        gap: int,
        reporter: ContactProgressReporter,
    ) -> list[ContactDiscoveryItem]:
        provider = self._require_search_provider()
        results = []
        self._last_query_trace: list[dict[str, object]] = []
        searches = self._searches(company, role)
        seen_urls: set[str] = set()
        for index, (search_kind, query) in enumerate(searches, start=1):
            if search_kind == "people":
                found = provider.search_people(
                    query, country="US", num_results=self._results_per_query
                )
            else:
                found = provider.search_contact_evidence(
                    query, country="US", num_results=self._results_per_query
                )
            self._repository.add_query(
                run_id,
                str(company["company_domain"]),
                role.key,
                query,
                found,
                provider.last_cost_dollars,
            )
            self._last_query_trace.append({"query": query, "result_count": len(found)})
            for result in found:
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    results.append(result)
            reporter.search(role.key, index, len(searches), len(results))

        assessments = self._require_evaluator().evaluate(
            ContactSearchBatch(
                company_name=str(company["company_name"]),
                company_domain=str(company["company_domain"]),
                role_key=role.key,
                role_labels=role.labels,
                results=results,
            ),
            current_only=spec.current_only,
            require_role_match=spec.require_role_match,
        )
        items: list[ContactDiscoveryItem] = []
        seen_identities: set[str] = set()
        accepted = 0
        for assessment in assessments:
            normalized_name = normalize_person_name(assessment.full_name)
            identity_key = contact_identity_key(normalized_name, assessment.linkedin_url)
            if identity_key in seen_identities or len(normalized_name.split()) < 2:
                continue
            seen_identities.add(identity_key)
            verdict = assessment.verdict
            reason = assessment.reason
            if verdict == ContactVerdict.ACCEPTED and accepted >= gap:
                verdict = ContactVerdict.REVIEW
                reason = f"{reason}; valid match held for review because role cap was reached"
            if verdict == ContactVerdict.ACCEPTED:
                accepted += 1
            candidate = ContactCandidate(
                company_id=int(company["company_id"]),
                company_name=str(company["company_name"]),
                company_domain=str(company["company_domain"]),
                full_name=assessment.full_name,
                normalized_name=normalized_name,
                identity_key=identity_key,
                title=assessment.title,
                linkedin_url=assessment.linkedin_url,
                source_urls=assessment.source_urls,
                evidence=assessment.evidence,
            )
            candidate_id = self._repository.upsert_candidate(candidate)
            items.append(
                ContactDiscoveryItem(
                    candidate_id=candidate_id,
                    candidate=candidate,
                    role_key=role.key,
                    verdict=verdict,
                    reason=reason,
                    current_company_match=assessment.current_company_match,
                    role_match=assessment.role_match,
                    identity_clear=assessment.identity_clear,
                    source="exa",
                )
            )
        reporter.evaluation(
            role.key,
            sum(item.verdict == ContactVerdict.ACCEPTED for item in items),
            sum(item.verdict == ContactVerdict.REVIEW for item in items),
            sum(item.verdict == ContactVerdict.REJECTED for item in items),
        )
        return items

    @staticmethod
    def _searches(
        company: dict[str, object], role: ContactRoleTarget
    ) -> list[tuple[str, str]]:
        labels = " OR ".join(f'"{label}"' for label in role.labels)
        company_name = str(company["company_name"])
        domain = str(company["company_domain"])
        return [
            (
                "people",
                f'People currently working at "{company_name}" ({domain}) as {labels}',
            ),
            ("evidence", f'site:{domain} {labels} team staff leadership'),
        ]

    @staticmethod
    def _limit_reached(spec: ContactSearchSpec, accepted_ids: set[int]) -> bool:
        return spec.contact_limit is not None and len(accepted_ids) >= spec.contact_limit

    @staticmethod
    def _best_verdicts(items: list[ContactDiscoveryItem]) -> dict[int, ContactVerdict]:
        rank = {
            ContactVerdict.REJECTED: 0,
            ContactVerdict.REVIEW: 1,
            ContactVerdict.ACCEPTED: 2,
        }
        best: dict[int, ContactVerdict] = {}
        for item in items:
            current = best.get(item.candidate_id, ContactVerdict.REJECTED)
            if rank[item.verdict] >= rank[current]:
                best[item.candidate_id] = item.verdict
        return best

    def _require_search_provider(self) -> ContactSearchProvider:
        if self._search_provider is None:
            raise RuntimeError("EXA_API_KEY is required when contact memory leaves role gaps")
        return self._search_provider

    def _require_evaluator(self) -> ContactEvaluator:
        if self._evaluator is None:
            raise RuntimeError("LLM_API_KEY is required when contact memory leaves role gaps")
        return self._evaluator
