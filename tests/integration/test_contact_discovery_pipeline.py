from __future__ import annotations

import csv
import json
from pathlib import Path

from company_discovery.db.contact_repository import ContactDiscoveryRepository
from company_discovery.db.enrichment_repository import EnrichmentRepository
from company_discovery.db.repository import DiscoveryRepository
from company_discovery.domain.contact_models import (
    ContactAssessment,
    ContactVerdict,
    EvidenceVerdict,
    ContactSearchBatch,
)
from company_discovery.domain.contact_spec import ContactSearchSpec
from company_discovery.domain.models import (
    CandidateBucket,
    CandidateEvaluation,
    EnrichmentItem,
    EnrichmentOutcome,
    EnrichmentProfile,
    EnrichmentSummary,
    ExaSearchResult,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    NormalizedCandidate,
    RunSummary,
)
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.contact_exporter import ContactDiscoveryArtifactExporter
from company_discovery.services.contact_pipeline import ContactDiscoveryPipeline


class FakePeopleSearch:
    def __init__(self) -> None:
        self.calls = 0
        self.last_cost_dollars = 0.01

    def search_people(
        self, query: str, *, country: str, num_results: int
    ) -> list[ExaSearchResult]:
        self.calls += 1
        return [
            ExaSearchResult(
                query=query,
                position=1,
                title="Jane Smith - Project Manager - Acme Builders",
                url="https://www.linkedin.com/in/jane-smith",
                text="Jane Smith is a Project Manager at Acme Builders.",
            )
        ]

    def search_contact_evidence(
        self, query: str, *, country: str, num_results: int
    ) -> list[ExaSearchResult]:
        self.calls += 1
        return [
            ExaSearchResult(
                query=query,
                position=1,
                title="Our Team - Acme Builders",
                url="https://acme.com/team/jane-smith",
                text="Jane Smith is a Project Manager at Acme Builders.",
            )
        ]


class FakeContactEvaluator:
    def evaluate(
        self,
        batch: ContactSearchBatch,
        *,
        current_only: bool,
        require_role_match: bool,
    ) -> list[ContactAssessment]:
        return [
            ContactAssessment(
                full_name="Jane Smith",
                title="Project Manager",
                linkedin_url="https://www.linkedin.com/in/jane-smith",
                source_urls=["https://www.linkedin.com/in/jane-smith"],
                evidence=["Project Manager at Acme Builders"],
                current_company_match=EvidenceVerdict.YES,
                role_match=EvidenceVerdict.YES,
                identity_clear=True,
                verdict=ContactVerdict.ACCEPTED,
                reason="Current company and requested role are explicit.",
            )
        ]


def _completed_company_enrichment(repository: DiscoveryRepository) -> str:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 1,
            "vertical": {
                "mode": "known",
                "key": "construction",
                "label": "Construction",
            },
        }
    )
    discovery_run_id = repository.create_run(spec)
    candidate_id = repository.upsert_candidate(
        NormalizedCandidate(
            company_name="Acme Builders",
            domain="acme.com",
            dedupe_key="acme.com",
            vertical="construction",
            country="US",
            state="TX",
        )
    )
    repository.record_evaluation(
        discovery_run_id,
        candidate_id,
        CandidateEvaluation(
            company_name="Acme Builders",
            domain="acme.com",
            fit=FitVerdict.GOOD,
            vertical_match=MatchVerdict.YES,
            geography_match=MatchVerdict.YES,
            size_match=MatchVerdict.UNKNOWN,
            excluded=ExclusionVerdict.NO,
            reason="Matches the target",
            reason_codes=[],
            evidence=["Texas builder"],
            inferred_vertical="construction",
            inferred_country="US",
            inferred_state="TX",
            inferred_employee_min=None,
            inferred_employee_max=None,
            inferred_ownership_type="independent",
            target_vertical="construction",
        ),
        CandidateBucket.SELECTED,
        "exa",
    )
    repository.complete_run(discovery_run_id, RunSummary(selected=1), {})

    enrichment_repository = EnrichmentRepository(repository.database)
    enrichment_run_id = enrichment_repository.create_run(
        discovery_run_id, "selected", {}
    )
    enrichment_repository.save_item(
        enrichment_run_id,
        EnrichmentItem(
            company_id=candidate_id,
            discovery={
                "run_id": discovery_run_id,
                "company_name": "Acme Builders",
                "domain": "acme.com",
                "vertical": "construction",
                "target_vertical": "construction",
                "country": "US",
                "state": "TX",
            },
            enrichment=EnrichmentProfile(),
            inherited_status={},
            outcome=EnrichmentOutcome.READY,
        ),
    )
    enrichment_repository.complete_run(
        enrichment_run_id, EnrichmentSummary(processed=1, ready=1), {}
    )
    return enrichment_run_id


def _contact_spec(enrichment_run_id: str) -> ContactSearchSpec:
    return ContactSearchSpec.model_validate(
        {
            "version": 1,
            "company_source": {"enrichment_run_id": enrichment_run_id},
            "roles": [
                {
                    "key": "project_manager",
                    "labels": ["project manager", "senior project manager"],
                    "max_per_company": 1,
                }
            ],
        }
    )


def test_contact_discovery_searches_exports_trace_and_reuses_memory(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    enrichment_run_id = _completed_company_enrichment(repository)
    contact_repository = ContactDiscoveryRepository(repository.database)
    search = FakePeopleSearch()
    pipeline = ContactDiscoveryPipeline(
        repository=contact_repository,
        exporter=ContactDiscoveryArtifactExporter(tmp_path / "runs"),
        search_provider=search,
        evaluator=FakeContactEvaluator(),  # type: ignore[arg-type]
        results_per_query=5,
    )

    first = pipeline.discover(_contact_spec(enrichment_run_id))

    assert first.run_id == "contact-discovery-run-1"
    assert first.summary.companies_loaded == 1
    assert first.summary.queries_run == 2
    assert first.summary.raw_results == 2
    assert first.summary.accepted == 1
    assert search.calls == 2
    accepted_path = Path(first.artifact_paths["accepted"])
    assert accepted_path.parent.name == "contact-discovery-run-1"
    assert accepted_path.parent.parent.name == "contacts"
    assert accepted_path.parent.parent.parent.name == enrichment_run_id
    assert accepted_path.parent.parent.parent.parent.name == "enrichment"
    with Path(first.artifact_paths["accepted"]).open() as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ContactDiscoveryArtifactExporter.FIELDS
    assert rows[0] == {
        "company_name": "Acme Builders",
        "company_domain": "acme.com",
        "contact_name": "Jane Smith",
        "title": "Project Manager",
        "linkedin_url": "https://www.linkedin.com/in/jane-smith",
        "email": "",
        "phone": "",
        "status": "accepted",
        "notes": "project_manager: Current company and requested role are explicit.",
    }
    payload = json.loads(Path(first.artifact_paths["json"]).read_text())
    assert payload["source_discovery_run_id"] == accepted_path.parent.parent.parent.parent.parent.name
    assert len(payload["queries"]) == 2
    assert payload["queries"][0]["raw_results"][0]["text"].startswith("Jane Smith")
    assert payload["items"][0]["candidate"]["evidence"] == [
        "Project Manager at Acme Builders"
    ]

    memory_only = ContactDiscoveryPipeline(
        repository=contact_repository,
        exporter=ContactDiscoveryArtifactExporter(tmp_path / "runs"),
        search_provider=None,
        evaluator=None,
    )
    second = memory_only.discover(_contact_spec(enrichment_run_id))

    assert second.run_id == "contact-discovery-run-2"
    assert second.summary.memory_reused == 1
    assert second.summary.queries_run == 0
    assert second.summary.accepted == 1
    assert second.items[0].source == "memory"


def test_contact_spec_rejects_domains_outside_the_selected_enrichment_bucket(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    enrichment_run_id = _completed_company_enrichment(repository)
    payload = _contact_spec(enrichment_run_id).model_dump()
    payload["company_source"]["domains"] = ["other.com"]
    spec = ContactSearchSpec.model_validate(payload)
    pipeline = ContactDiscoveryPipeline(
        repository=ContactDiscoveryRepository(repository.database),
        exporter=ContactDiscoveryArtifactExporter(tmp_path / "runs"),
        search_provider=None,
        evaluator=None,
    )

    try:
        pipeline.discover(spec)
    except ValueError as exc:
        assert "other.com" in str(exc)
    else:
        raise AssertionError("out-of-scope domain should fail before contact discovery")
