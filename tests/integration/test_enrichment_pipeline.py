from __future__ import annotations

import csv
import json
from pathlib import Path

from company_discovery.db.enrichment_repository import EnrichmentRepository
from company_discovery.db.repository import DiscoveryRepository
from company_discovery.domain.models import (
    CandidateBucket,
    CandidateEvaluation,
    EnrichmentExtraction,
    ExclusionVerdict,
    FitVerdict,
    LocationObservation,
    MatchVerdict,
    NormalizedCandidate,
    OwnershipSignal,
    PhoneObservation,
    RunSummary,
    WebsitePage,
)
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.enrichment_exporter import EnrichmentArtifactExporter
from company_discovery.services.enrichment_pipeline import EnrichmentPipeline


class FakeWebsite:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, domain: str) -> list[WebsitePage]:
        self.calls += 1
        return [
            WebsitePage(
                url=f"https://{domain}/contact",
                page_type="contact",
                text="Acme Builders, (210) 555-1234, 10 Main St, Austin TX 78701",
                linkedin_urls=[
                    "https://www.linkedin.com/company/acme-builders/?trk=website"
                ],
            ),
            WebsitePage(
                url=f"https://{domain}/about",
                page_type="about",
                text="Acme Builders is a family-owned construction company.",
            ),
        ]


class NoLinkedInWebsite(FakeWebsite):
    def fetch(self, domain: str) -> list[WebsitePage]:
        return [
            page.model_copy(update={"linkedin_urls": []})
            for page in super().fetch(domain)
        ]


class FakeExtractor:
    def extract(self, discovery: dict[str, object], pages: list[WebsitePage]) -> EnrichmentExtraction:
        domain = str(discovery["domain"])
        return EnrichmentExtraction(
            observed_company_name="Acme Builders",
            phones=[
                PhoneObservation(
                    value="(210) 555-1234",
                    label="main",
                    source_url=f"https://{domain}/contact",
                )
            ],
            locations=[
                LocationObservation(
                    street_address="99 Wrong Way",
                    city="Denver",
                    state="CO",
                    zip="80202",
                    source_url=f"https://{domain}/locations",
                ),
                LocationObservation(
                    street_address="10 Main St",
                    city="Austin",
                    state="Texas",
                    zip="78701",
                    source_url=f"https://{domain}/contact",
                ),
            ],
            ownership_signals=[
                OwnershipSignal(
                    kind="family_owned",
                    statement="The official about page states the company is family-owned.",
                    source_url=f"https://{domain}/about",
                )
            ],
        )


class UnknownIndependenceExtractor(FakeExtractor):
    def extract(self, discovery: dict[str, object], pages: list[WebsitePage]) -> EnrichmentExtraction:
        result = super().extract(discovery, pages)
        return result.model_copy(update={"ownership_signals": []})


def _completed_discovery(
    repository: DiscoveryRepository,
    *,
    excluded_ownership_signals: list[str] | None = None,
) -> str:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 1,
            "vertical": {"key": "construction", "label": "Construction"},
            "geography": {"country": "US", "states": ["TX"]},
            "company_size": {"employee_min": 10, "employee_max": 50},
            "exclude": {
                "structured": {
                    "ownership_signals": excluded_ownership_signals or [],
                }
            },
        }
    )
    run_id = repository.create_run(spec)
    candidate_id = repository.upsert_candidate(
        NormalizedCandidate(
            company_name="Acme Builders",
            domain="acme.com",
            dedupe_key="acme.com",
            vertical="construction",
            country="US",
            state="TX",
            employee_min=20,
            employee_max=30,
            ownership_type="privately_held",
        )
    )
    repository.record_evaluation(
        run_id,
        candidate_id,
        CandidateEvaluation(
            company_name="Acme Builders",
            domain="acme.com",
            fit=FitVerdict.GOOD,
            vertical_match=MatchVerdict.YES,
            geography_match=MatchVerdict.YES,
            size_match=MatchVerdict.YES,
            excluded=ExclusionVerdict.NO,
            reason="Matches the Texas construction ICP",
            reason_codes=[],
            evidence=["Texas construction company"],
            inferred_vertical="construction",
            inferred_country="US",
            inferred_state="TX",
            inferred_employee_min=20,
            inferred_employee_max=30,
            inferred_ownership_type="privately_held",
            target_vertical="construction",
        ),
        CandidateBucket.SELECTED,
        "external",
    )
    repository.complete_run(run_id, RunSummary(selected=1), {})
    return run_id


def test_enrichment_inherits_discovery_resolves_state_and_reuses_memory(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    discovery_run_id = _completed_discovery(repository)
    enrichment_repository = EnrichmentRepository(repository.database)
    website = FakeWebsite()
    pipeline = EnrichmentPipeline(
        repository=enrichment_repository,
        exporter=EnrichmentArtifactExporter(tmp_path / "runs"),
        website=website,
        extractor=FakeExtractor(),
    )

    first = pipeline.enrich(discovery_run_id)

    assert first.run_id.startswith("company-enrich-")
    assert first.summary.ready == 1
    assert first.items[0].enrichment.location is not None
    assert first.items[0].enrichment.location.state == "TX"
    assert first.items[0].enrichment.location.street_address == "10 Main St"
    assert first.items[0].enrichment.independence is not None
    assert first.items[0].enrichment.independence.status == "yes"
    assert first.items[0].enrichment.linkedin is not None
    assert first.items[0].enrichment.linkedin.url == (
        "https://www.linkedin.com/company/acme-builders"
    )
    assert first.items[0].enrichment.linkedin.source_url == "https://acme.com/contact"
    with Path(first.artifact_paths["enriched"]).open() as handle:
        rows = list(csv.DictReader(handle))
    enriched_path = Path(first.artifact_paths["enriched"])
    assert enriched_path.parent.name == first.run_id
    assert enriched_path.parent.parent.name == "enrich"
    assert enriched_path.parent.parent.parent.name == discovery_run_id
    assert rows[0]["linkedin_url"] == "https://www.linkedin.com/company/acme-builders"
    assert rows[0]["phone"] == "(210) 555-1234"
    assert rows[0]["vertical"] == "construction"
    assert rows[0]["ownership_type"] == "privately_held"
    payload = json.loads(Path(first.artifact_paths["json"]).read_text())
    assert payload["items"][0]["trace"][0]["stage"] == "inherited"
    stored = enrichment_repository.get_run(first.run_id)
    assert stored["discovery_run_id"] == discovery_run_id
    assert stored["items"][0]["discovery"]["domain"] == "acme.com"
    assert enrichment_repository.inspect_item(first.run_id, "acme.com")["outcome"] == "enriched_ready"

    second = pipeline.enrich(discovery_run_id)

    assert second.run_id.startswith("company-enrich-")
    assert second.run_id != first.run_id
    assert website.calls == 1
    assert second.summary.memory_profiles_reused == 1
    assert second.summary.websites_fetched == 0
    assert second.summary.ready == 1


def test_fresh_unknown_independence_is_reused_without_repeated_fetch(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    discovery_run_id = _completed_discovery(repository)
    website = FakeWebsite()
    pipeline = EnrichmentPipeline(
        repository=EnrichmentRepository(repository.database),
        exporter=EnrichmentArtifactExporter(tmp_path / "runs"),
        website=website,
        extractor=UnknownIndependenceExtractor(),
    )

    first = pipeline.enrich(discovery_run_id)
    second = pipeline.enrich(discovery_run_id)

    assert first.summary.review == 1
    assert first.items[0].outcome == "independence_unconfirmed"
    assert second.summary.memory_profiles_reused == 1
    assert second.summary.websites_fetched == 0
    assert website.calls == 1


def test_missing_linkedin_profile_is_reported_as_an_enrichment_gap(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    discovery_run_id = _completed_discovery(repository)
    pipeline = EnrichmentPipeline(
        repository=EnrichmentRepository(repository.database),
        exporter=EnrichmentArtifactExporter(tmp_path / "runs"),
        website=NoLinkedInWebsite(),
        extractor=FakeExtractor(),
    )

    result = pipeline.enrich(discovery_run_id)

    assert result.summary.review == 1
    assert result.items[0].outcome == "enriched_with_gaps"
    assert result.items[0].review_flags == ["linkedin_missing"]


def test_enrichment_blocks_family_owned_when_requested_and_reuses_signal_memory(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    discovery_run_id = _completed_discovery(
        repository,
        excluded_ownership_signals=["family_owned"],
    )
    website = FakeWebsite()
    pipeline = EnrichmentPipeline(
        repository=EnrichmentRepository(repository.database),
        exporter=EnrichmentArtifactExporter(tmp_path / "runs"),
        website=website,
        extractor=FakeExtractor(),
    )

    first = pipeline.enrich(discovery_run_id)
    second = pipeline.enrich(discovery_run_id)

    assert first.summary.blocked == 1
    assert first.items[0].outcome == "fit_conflict"
    assert first.items[0].review_flags == ["excluded_family_owned"]
    assert "excluded_ownership_signal: family_owned" in first.items[0].conflicts
    assert first.items[0].trace[-2] == {
        "stage": "structured_exclusions",
        "requested": ["family_owned"],
        "matched": ["family_owned"],
    }
    with Path(first.artifact_paths["blocked"]).open() as handle:
        blocked_rows = list(csv.DictReader(handle))
    assert blocked_rows[0]["conflicts"] == "excluded_ownership_signal: family_owned"
    assert blocked_rows[0]["review_flags"] == "excluded_family_owned"
    assert second.summary.blocked == 1
    assert second.summary.memory_profiles_reused == 1
    assert website.calls == 1
