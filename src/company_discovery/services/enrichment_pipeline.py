from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from company_discovery.adapters.protocols import CompanySearchProvider
from company_discovery.db.enrichment_repository import EnrichmentRepository
from company_discovery.domain.models import (
    EnrichmentExtraction,
    EnrichmentItem,
    EnrichmentOutcome,
    EnrichmentProfile,
    EnrichmentRunResult,
    EnrichmentSummary,
    IndependenceStatus,
    InheritedFieldStatus,
    LinkedInObservation,
    WebsitePage,
)
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.enrichment_exporter import EnrichmentArtifactExporter
from company_discovery.services.enrichment_progress import (
    EnrichmentProgressReporter,
    NullEnrichmentProgressReporter,
)
from company_discovery.services.enrichment_resolver import (
    normalize_linkedin_company_url,
    resolve_independence,
    resolve_linkedin,
    resolve_location,
    resolve_phone,
)


class WebsiteRetriever(Protocol):
    def fetch(self, domain: str) -> list[WebsitePage]: ...


class FactExtractor(Protocol):
    def extract(
        self, discovery: dict[str, object], pages: list[WebsitePage]
    ) -> EnrichmentExtraction: ...


@dataclass(frozen=True)
class EnrichmentOptions:
    bucket: str = "selected"
    limit: int | None = None
    refresh: str = "none"
    allow_unknown_independence: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "limit": self.limit,
            "refresh": self.refresh,
            "allow_unknown_independence": self.allow_unknown_independence,
        }


class EnrichmentPipeline:
    def __init__(
        self,
        *,
        repository: EnrichmentRepository,
        exporter: EnrichmentArtifactExporter,
        website: WebsiteRetriever | None,
        extractor: FactExtractor | None,
        fallback_search: CompanySearchProvider | None = None,
        freshness_days: int = 180,
        fallback_results: int = 5,
    ) -> None:
        self._repository = repository
        self._exporter = exporter
        self._website = website
        self._extractor = extractor
        self._fallback_search = fallback_search
        self._freshness_days = freshness_days
        self._fallback_results = fallback_results

    def enrich(
        self,
        discovery_run_id: str,
        *,
        options: EnrichmentOptions | None = None,
        progress: EnrichmentProgressReporter | None = None,
    ) -> EnrichmentRunResult:
        options = options or EnrichmentOptions()
        reporter = progress or NullEnrichmentProgressReporter()
        candidates = self._repository.discovery_candidates(
            discovery_run_id, options.bucket, options.limit
        )
        run_id = self._repository.create_run(discovery_run_id, options.bucket, options.as_dict())
        try:
            return self._run(run_id, discovery_run_id, candidates, options, reporter)
        except Exception as exc:
            self._repository.fail_run(run_id, exc)
            raise

    def _run(
        self,
        run_id: str,
        discovery_run_id: str,
        candidates: list[dict[str, object]],
        options: EnrichmentOptions,
        reporter: EnrichmentProgressReporter,
    ) -> EnrichmentRunResult:
        summary = EnrichmentSummary()
        items: list[EnrichmentItem] = []
        reporter.start(discovery_run_id, len(candidates), options.bucket)
        for index, record in enumerate(candidates, start=1):
            item = self._enrich_one(
                run_id, discovery_run_id, record, options, reporter, index, len(candidates), summary
            )
            items.append(item)
            self._repository.save_item(run_id, item)
            self._count_outcome(summary, item.outcome)

        payload = {
            "run_id": run_id,
            "discovery_run_id": discovery_run_id,
            "bucket": options.bucket,
            "options": options.as_dict(),
            "status": "completed",
            "items": [item.model_dump(mode="json") for item in items],
        }
        paths = self._exporter.export(payload, summary)
        self._repository.complete_run(run_id, summary, paths)
        return EnrichmentRunResult(
            run_id=run_id,
            discovery_run_id=discovery_run_id,
            summary=summary,
            items=items,
            artifact_paths=paths,
        )

    def _enrich_one(
        self,
        run_id: str,
        discovery_run_id: str,
        record: dict[str, object],
        options: EnrichmentOptions,
        reporter: EnrichmentProgressReporter,
        index: int,
        total: int,
        summary: EnrichmentSummary,
    ) -> EnrichmentItem:
        company = dict(record["company"])  # type: ignore[arg-type]
        evaluation = dict(record["evaluation"])  # type: ignore[arg-type]
        spec = CompanySearchSpec.model_validate(record["spec"])
        excluded_ownership_signals = {
            signal.value for signal in spec.exclude.structured.ownership_signals
        }
        discovery = {
            "run_id": discovery_run_id,
            "company_name": company["company_name"],
            "domain": company["domain"],
            "vertical": company.get("vertical"),
            "target_vertical": evaluation.get("target_vertical") or company.get("vertical"),
            "country": company.get("country"),
            "state": company.get("state"),
            "employee_min": company.get("employee_min"),
            "employee_max": company.get("employee_max"),
            "ownership_type": company.get("ownership_type"),
            "fit": evaluation.get("fit"),
            "reason": evaluation.get("reason"),
            "evidence": evaluation.get("evidence", []),
            "source": record["source"],
            "excluded_ownership_signals": sorted(excluded_ownership_signals),
        }
        reporter.company(index, total, str(discovery["company_name"]))
        reporter.event("INHERITED", "name, domain, vertical, geography, employees, ownership type")
        summary.processed += 1
        summary.inherited_facts += 7
        trace: list[dict[str, object]] = [
            {"stage": "inherited", "fields": [
                "company_name", "domain", "vertical", "geography", "employees", "ownership_type"
            ]}
        ]
        candidate_id = int(record["candidate_id"])  # type: ignore[arg-type]
        profile = self._repository.fresh_profile(candidate_id, self._freshness_days)
        profile = self._apply_refresh(profile, options.refresh)
        reused = sum(
            value is not None
            for value in (profile.phone, profile.location, profile.independence, profile.linkedin)
        )
        if reused:
            summary.memory_profiles_reused += 1
            reporter.event("MEMORY", f"reused {reused}/4 fresh enrichment facts")
            trace.append({"stage": "memory", "reused": reused})
        else:
            reporter.event("MEMORY", "no reusable enrichment profile")
            trace.append({"stage": "memory", "reused": 0})

        conflicts: list[str] = []
        statuses = {
            key: InheritedFieldStatus.INHERITED
            for key in (
                "company_name", "domain", "vertical", "country", "state",
                "employee_estimate", "ownership_type"
            )
        }
        # A fresh explicit `unknown` independence result is reusable until its freshness window
        # expires; only a newly fetched unknown result should trigger corroboration in this run.
        try:
            missing = self._missing(profile, include_unknown_independence=False)
            if missing:
                pages = self._fetch_pages(str(discovery["domain"]))
                if pages:
                    summary.websites_fetched += 1
                    reporter.event("WEBSITE", f"read {len(pages)} targeted official pages")
                    trace.append({"stage": "website", "pages": [page.url for page in pages]})
                    extraction = self._extract(discovery, pages)
                    profile, new_conflicts = self._merge(
                        profile, extraction, discovery, "official_site"
                    )
                    conflicts.extend(new_conflicts)
                    self._confirm_inherited(statuses, extraction, discovery, profile)

            missing = self._missing(profile, include_unknown_independence=True)
            if missing and self._fallback_search is not None and self._extractor is not None:
                for query, fields in self._fallback_queries(discovery, missing):
                    results = self._fallback_search.search(
                        query,
                        country=str(discovery.get("country") or "US"),
                        num_results=self._fallback_results,
                    )
                    summary.fallback_searches += 1
                    reporter.event("FALLBACK", f"narrow corroboration for {', '.join(fields)}")
                    pages = [
                        WebsitePage(
                            url=result.url,
                            title=result.title,
                            text=result.text or "",
                            page_type="search_evidence",
                        )
                        for result in results
                        if result.text or normalize_linkedin_company_url(result.url)
                    ]
                    trace.append({
                        "stage": "fallback",
                        "query": query,
                        "fields": fields,
                        "sources": [page.url for page in pages],
                    })
                    if pages:
                        extraction = self._extract(discovery, pages)
                        profile, new_conflicts = self._merge(
                            profile, extraction, discovery, "search_corroboration"
                        )
                        conflicts.extend(new_conflicts)
        except Exception as exc:
            if self._is_configuration_error(exc):
                raise
            return self._failed_item(
                candidate_id,
                discovery,
                profile,
                statuses,
                conflicts,
                trace,
                exc,
                reporter,
            )

        matched_exclusions = self._matched_ownership_exclusions(
            profile, excluded_ownership_signals
        )
        conflicts.extend(
            f"excluded_ownership_signal: {signal}" for signal in matched_exclusions
        )
        trace.append({
            "stage": "structured_exclusions",
            "requested": sorted(excluded_ownership_signals),
            "matched": matched_exclusions,
        })
        outcome, review_flags = self._outcome(
            profile,
            conflicts,
            options.allow_unknown_independence,
            matched_exclusions,
        )
        label = "READY" if outcome == EnrichmentOutcome.READY else "REVIEW" if outcome in {
            EnrichmentOutcome.GAPS, EnrichmentOutcome.INDEPENDENCE_UNCONFIRMED
        } else "BLOCKED"
        reporter.event(label, outcome.value)
        trace.append({"stage": "outcome", "value": outcome.value})
        return EnrichmentItem(
            company_id=candidate_id,
            discovery=discovery,
            enrichment=profile,
            inherited_status=statuses,
            outcome=outcome,
            conflicts=list(dict.fromkeys(conflicts)),
            review_flags=review_flags,
            trace=trace,
        )

    def _failed_item(
        self,
        candidate_id: int,
        discovery: dict[str, object],
        profile: EnrichmentProfile,
        statuses: dict[str, InheritedFieldStatus],
        conflicts: list[str],
        trace: list[dict[str, object]],
        error: Exception,
        reporter: EnrichmentProgressReporter,
    ) -> EnrichmentItem:
        message = self._error_message(error)
        reporter.event("FAILED", message)
        trace.append({
            "stage": "error",
            "error_type": type(error).__name__,
            "message": message,
        })
        return EnrichmentItem(
            company_id=candidate_id,
            discovery=discovery,
            enrichment=profile,
            inherited_status=statuses,
            outcome=EnrichmentOutcome.FAILED,
            conflicts=list(dict.fromkeys([*conflicts, f"enrichment_failed: {message}"])),
            review_flags=["enrichment_failed"],
            trace=trace,
        )

    def _fetch_pages(self, domain: str) -> list[WebsitePage]:
        if self._website is None:
            return []
        return self._website.fetch(domain)

    def _extract(
        self, discovery: dict[str, object], pages: list[WebsitePage]
    ) -> EnrichmentExtraction:
        if self._extractor is None:
            raise RuntimeError("LLM_API_KEY is required to extract enrichment facts")
        extraction = self._extractor.extract(discovery, pages)
        linkedin_profiles = list(extraction.linkedin_profiles)
        seen = {profile.url for profile in linkedin_profiles}
        for page in pages:
            # Only official-site anchors are deterministic. Search-result URLs require the
            # extractor's company/domain identity check before they become observations.
            for candidate in page.linkedin_urls:
                normalized = normalize_linkedin_company_url(candidate)
                if normalized is not None and normalized not in seen:
                    linkedin_profiles.append(
                        LinkedInObservation(url=normalized, source_url=page.url)
                    )
                    seen.add(normalized)
        return extraction.model_copy(update={"linkedin_profiles": linkedin_profiles})

    @staticmethod
    def _apply_refresh(profile: EnrichmentProfile, refresh: str) -> EnrichmentProfile:
        updates: dict[str, object] = {}
        if refresh in {"contact", "all"}:
            updates.update(phone=None, location=None, linkedin=None)
        if refresh in {"independence", "all"}:
            updates["independence"] = None
        return profile.model_copy(update=updates)

    @staticmethod
    def _missing(
        profile: EnrichmentProfile,
        *,
        include_unknown_independence: bool,
    ) -> list[str]:
        missing = []
        if profile.phone is None:
            missing.append("phone")
        if profile.location is None:
            missing.append("address")
        if profile.linkedin is None:
            missing.append("linkedin")
        if profile.independence is None or (
            include_unknown_independence
            and profile.independence.status == IndependenceStatus.UNKNOWN
        ):
            missing.append("independence")
        return missing

    @staticmethod
    def _merge(
        profile: EnrichmentProfile,
        extraction: EnrichmentExtraction,
        discovery: dict[str, object],
        source: str,
    ) -> tuple[EnrichmentProfile, list[str]]:
        conflicts: list[str] = []
        if extraction.identity_conflict:
            conflicts.append(f"identity_conflict: {extraction.identity_conflict_reason or 'source mismatch'}")
        phone = profile.phone or resolve_phone(extraction, source)
        location = profile.location
        if location is None:
            location, _ = resolve_location(
                extraction, discovery.get("state"), source  # type: ignore[arg-type]
            )
        independence = profile.independence
        resolved_independence = resolve_independence(extraction)
        if independence is None or independence.status == IndependenceStatus.UNKNOWN:
            independence = resolved_independence
        if independence.status == IndependenceStatus.NO:
            conflicts.append("independence_conflict: explicit parent, franchise, or acquisition evidence")
        linkedin = profile.linkedin or resolve_linkedin(extraction, source)
        return EnrichmentProfile(
            phone=phone,
            location=location,
            independence=independence,
            linkedin=linkedin,
        ), conflicts

    @staticmethod
    def _confirm_inherited(
        statuses: dict[str, InheritedFieldStatus],
        extraction: EnrichmentExtraction,
        discovery: dict[str, object],
        profile: EnrichmentProfile,
    ) -> None:
        if extraction.observed_company_name and not extraction.identity_conflict:
            statuses["company_name"] = InheritedFieldStatus.CONFIRMED
            statuses["domain"] = InheritedFieldStatus.CONFIRMED
        if profile.location is not None and profile.location.state == discovery.get("state"):
            statuses["country"] = InheritedFieldStatus.CONFIRMED
            statuses["state"] = InheritedFieldStatus.CONFIRMED
        if extraction.identity_conflict:
            statuses["company_name"] = InheritedFieldStatus.CONFLICT
            statuses["domain"] = InheritedFieldStatus.CONFLICT

    @staticmethod
    def _fallback_query(discovery: dict[str, object], missing: list[str]) -> str:
        return (
            f'"{discovery["company_name"]}" site:{discovery["domain"]} '
            f'{" ".join(missing)} contact address franchise parent ownership'
        )

    @classmethod
    def _fallback_queries(
        cls,
        discovery: dict[str, object],
        missing: list[str],
    ) -> list[tuple[str, list[str]]]:
        queries: list[tuple[str, list[str]]] = []
        standard_fields = [field for field in missing if field != "linkedin"]
        if standard_fields:
            queries.append((cls._fallback_query(discovery, standard_fields), standard_fields))
        if "linkedin" in missing:
            queries.append((
                f'"{discovery["company_name"]}" "{discovery["domain"]}" '
                "site:linkedin.com/company",
                ["linkedin"],
            ))
        return queries

    @staticmethod
    def _outcome(
        profile: EnrichmentProfile,
        conflicts: list[str],
        allow_unknown: bool,
        matched_exclusions: list[str] | None = None,
    ) -> tuple[EnrichmentOutcome, list[str]]:
        if any(value.startswith("identity_conflict") for value in conflicts):
            return EnrichmentOutcome.IDENTITY_CONFLICT, ["identity_conflict"]
        if any(value.startswith("geography_conflict") for value in conflicts):
            return EnrichmentOutcome.GEOGRAPHY_CONFLICT, ["geography_conflict"]
        if matched_exclusions:
            return EnrichmentOutcome.FIT_CONFLICT, [
                f"excluded_{signal}" for signal in matched_exclusions
            ]
        if profile.independence and profile.independence.status == IndependenceStatus.NO:
            return EnrichmentOutcome.FIT_CONFLICT, ["not_independent"]
        gaps = []
        if profile.phone is None:
            gaps.append("phone_missing")
        if profile.location is None:
            gaps.append("address_missing")
        if profile.linkedin is None:
            gaps.append("linkedin_missing")
        if gaps:
            return EnrichmentOutcome.GAPS, gaps
        if profile.independence is None or profile.independence.status == IndependenceStatus.UNKNOWN:
            if allow_unknown:
                return EnrichmentOutcome.READY, ["independence_unknown_allowed"]
            return EnrichmentOutcome.INDEPENDENCE_UNCONFIRMED, ["independence_unknown"]
        return EnrichmentOutcome.READY, []

    @staticmethod
    def _matched_ownership_exclusions(
        profile: EnrichmentProfile,
        excluded_signals: set[str],
    ) -> list[str]:
        if not excluded_signals or profile.independence is None:
            return []
        observed = set(profile.independence.signal_kinds)
        # Older cached facts predate signal_kinds. Preserve family-owned evidence across upgrades.
        if "family_owned" not in observed:
            evidence = " ".join(profile.independence.evidence).lower()
            if "family-owned" in evidence or "family owned" in evidence:
                observed.add("family_owned")
        return sorted(observed & excluded_signals)

    @staticmethod
    def _error_message(error: Exception) -> str:
        message = " ".join(str(error).split())
        if not message:
            message = type(error).__name__
        return message[:1000]

    @staticmethod
    def _is_configuration_error(error: Exception) -> bool:
        message = str(error)
        return (
            "LLM_API_KEY is required" in message
            or "LLM API returned HTTP 401" in message
            or "LLM API returned HTTP 403" in message
        )

    @staticmethod
    def _count_outcome(summary: EnrichmentSummary, outcome: EnrichmentOutcome) -> None:
        if outcome == EnrichmentOutcome.READY:
            summary.ready += 1
        elif outcome in {EnrichmentOutcome.GAPS, EnrichmentOutcome.INDEPENDENCE_UNCONFIRMED}:
            summary.review += 1
        elif outcome == EnrichmentOutcome.FAILED:
            summary.failed += 1
        else:
            summary.blocked += 1
