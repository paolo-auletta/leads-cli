from __future__ import annotations

from company_discovery.db.repository import MemoryRecord
from company_discovery.domain.models import (
    CandidateEvaluation,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    NormalizedCandidate,
)
from company_discovery.domain.spec import CompanySearchSpec, NoveltyMode
from company_discovery.services.memory import MemoryMatcher


def evaluation(fit: FitVerdict = FitVerdict.GOOD) -> CandidateEvaluation:
    return CandidateEvaluation(
        company_name="Acme",
        domain="acme.com",
        fit=fit,
        vertical_match=MatchVerdict.YES,
        geography_match=MatchVerdict.YES,
        size_match=MatchVerdict.YES,
        excluded=ExclusionVerdict.NO,
        reason="Fits",
        reason_codes=[],
        evidence=[],
        inferred_vertical="construction",
        inferred_country="US",
        inferred_state="TX",
        inferred_employee_min=20,
        inferred_employee_max=50,
        inferred_ownership_type=None,
    )


def record(
    candidate_id: int,
    *,
    vertical: str | None = "construction",
    country: str | None = "US",
    state: str | None = "TX",
    employee_min: int | None = 20,
    employee_max: int | None = 50,
    ownership: str | None = None,
    fit: FitVerdict | None = FitVerdict.GOOD,
    ever_selected: bool = False,
    latest_spec: CompanySearchSpec | None = None,
) -> MemoryRecord:
    candidate = NormalizedCandidate(
        company_name=f"Company {candidate_id}",
        domain=f"company{candidate_id}.com",
        dedupe_key=f"company{candidate_id}.com",
        vertical=vertical,
        country=country,
        state=state,
        employee_min=employee_min,
        employee_max=employee_max,
        ownership_type=ownership,
    )
    evaluated = evaluation(fit) if fit else None
    if evaluated:
        evaluated = evaluated.model_copy(
            update={"company_name": candidate.company_name, "domain": candidate.domain}
        )
    return MemoryRecord(
        candidate_id=candidate_id,
        candidate=candidate,
        latest_fit=fit.value if fit else None,
        latest_bucket="selected" if fit == FitVerdict.GOOD else "rejected",
        latest_reason="prior reason" if fit else None,
        latest_reason_codes=(),
        latest_evaluation=evaluated,
        ever_selected=ever_selected,
        latest_spec=latest_spec,
    )


def test_memory_separates_reusable_uncertain_and_hard_mismatches(spec: CompanySearchSpec) -> None:
    records = [
        record(1, latest_spec=spec),
        record(2, state=None, fit=FitVerdict.POSSIBLE, latest_spec=spec),
        record(3, state="CA", latest_spec=spec),
        record(4, employee_min=150, employee_max=300, latest_spec=spec),
        record(5, ownership="franchise", latest_spec=spec),
        record(6, vertical="healthcare", latest_spec=spec),
    ]

    result = MemoryMatcher().scan(spec, records)

    assert [item.candidate_id for item in result.reusable] == [1]
    assert [item.candidate_id for item in result.recheck] == [2]
    assert {item.reason for item in result.skipped} == {
        "state_mismatch",
        "size_above_maximum",
        "excluded_ownership",
        "vertical_mismatch",
    }


def test_default_memory_suppresses_previously_selected(spec: CompanySearchSpec) -> None:
    result = MemoryMatcher().scan(
        spec,
        [record(1, ever_selected=True, latest_spec=spec), record(2, latest_spec=spec)],
    )
    assert [item.candidate_id for item in result.reusable] == [2]
    assert result.skipped[0].reason == "previously_selected"


def test_only_new_bypasses_all_memory(spec: CompanySearchSpec) -> None:
    only_new = spec.model_copy(update={"novelty_mode": NoveltyMode.ONLY_NEW})
    result = MemoryMatcher().scan(
        only_new,
        [record(1, ever_selected=True, latest_spec=only_new), record(2, latest_spec=only_new)],
    )
    assert result.matched == 0
    assert result.reusable == []
    assert {item.reason for item in result.skipped} == {"memory_disabled_only_new"}


def test_full_memory_can_reuse_previously_selected(spec: CompanySearchSpec) -> None:
    full_memory = spec.model_copy(update={"novelty_mode": NoveltyMode.FULL_MEMORY})
    result = MemoryMatcher().scan(
        full_memory,
        [record(1, ever_selected=True, latest_spec=full_memory)],
    )
    assert [item.candidate_id for item in result.reusable] == [1]


def test_good_prior_fit_is_rechecked_when_required_structured_facts_are_missing(
    spec: CompanySearchSpec,
) -> None:
    result = MemoryMatcher().scan(
        spec,
        [
            record(1, state=None, latest_spec=spec),
            record(2, employee_min=None, employee_max=None, latest_spec=spec),
        ],
    )
    assert result.reusable == []
    assert [item.candidate_id for item in result.recheck] == [1, 2]


def test_new_exclusions_force_recheck_even_for_a_prior_good_fit(spec: CompanySearchSpec) -> None:
    prior = spec.model_copy(update={"exclude": spec.exclude.model_copy(update={"keywords": []})})
    item = record(1)
    item = MemoryRecord(**{**item.__dict__, "latest_spec": prior})
    result = MemoryMatcher().scan(spec, [item])
    assert result.reusable == []
    assert [candidate.candidate_id for candidate in result.recheck] == [1]


def test_prior_hard_reason_only_skips_when_relevant_constraint_is_unchanged(
    spec: CompanySearchSpec,
) -> None:
    prior = record(1, fit=FitVerdict.BAD, latest_spec=spec)
    prior = MemoryRecord(
        **{
            **prior.__dict__,
            "latest_reason_codes": ("size_mismatch",),
        }
    )
    same = MemoryMatcher().scan(spec, [prior])
    assert same.skipped[0].reason == "prior_size_mismatch_same_spec"

    changed = spec.model_copy(
        update={"company_size": spec.company_size.model_copy(update={"employee_max": 200})}
    )
    reconsidered = MemoryMatcher().scan(changed, [prior])
    assert [item.candidate_id for item in reconsidered.recheck] == [1]
