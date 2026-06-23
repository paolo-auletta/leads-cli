from __future__ import annotations

from company_discovery.db.repository import DiscoveryRepository
from company_discovery.domain.models import (
    CandidateBucket,
    CandidateEvaluation,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    NormalizedCandidate,
    RunSummary,
)
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.db.models import CompanyCandidateRow
from sqlalchemy import select


def test_repository_preserves_canonical_company_and_run_specific_history(
    repository: DiscoveryRepository,
    spec: CompanySearchSpec,
) -> None:
    candidate = NormalizedCandidate(company_name="Acme", domain="acme.com", dedupe_key="acme.com")
    candidate_id = repository.upsert_candidate(candidate)
    same_id = repository.upsert_candidate(
        candidate.model_copy(update={"company_name": "Acme Builders"})
    )
    assert same_id == candidate_id

    run_id = repository.create_run(spec)
    assert run_id.startswith("company-discover-")
    evaluation = CandidateEvaluation(
        company_name="Acme Builders",
        domain="acme.com",
        fit=FitVerdict.GOOD,
        vertical_match=MatchVerdict.YES,
        geography_match=MatchVerdict.YES,
        size_match=MatchVerdict.LIKELY,
        excluded=ExclusionVerdict.NO,
        reason="Fits",
        reason_codes=["verified"],
        evidence=["Official site"],
        inferred_vertical="construction",
        inferred_country="US",
        inferred_state="TX",
        inferred_employee_min=20,
        inferred_employee_max=50,
        inferred_ownership_type=None,
    )
    repository.record_evaluation(run_id, candidate_id, evaluation, CandidateBucket.SELECTED, "exa")
    repository.complete_run(run_id, RunSummary(selected=1), {})

    memory = repository.memory_records()
    assert len(memory) == 1
    assert memory[0].candidate.vertical == "construction"
    assert memory[0].candidate.state == "TX"
    assert memory[0].ever_selected is True
    with repository.database.session() as session:
        stored = session.scalar(select(CompanyCandidateRow).where(CompanyCandidateRow.id == candidate_id))
        assert stored is not None
        assert stored.prior_bucket == "selected"
        assert stored.prior_reason == "Fits"
    payload = repository.get_run(run_id)
    assert payload["candidates"][0]["evaluation"]["reason"] == "Fits"
