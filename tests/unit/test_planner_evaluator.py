from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from company_discovery.domain.models import (
    CandidateEvaluation,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    NormalizedCandidate,
    QueryPlan,
)
from company_discovery.domain.spec import CompanySearchSpec, ExternalSearchSpec
from company_discovery.services.evaluator import CandidateEvaluator
from company_discovery.services.query_planner import QueryPlanner


class CapturingLLM:
    def __init__(self) -> None:
        self.prompts: list[dict] = []

    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type[BaseModel]):
        self.prompts.append(json.loads(user_prompt))
        if response_model is QueryPlan:
            query_count = self.prompts[-1]["required_query_count"]
            return QueryPlan(
                queries=[f"query {index}" for index in range(query_count)],
                rationale="coverage",
            )
        return CandidateEvaluation(
            company_name="Wrong generated name",
            domain="wrong.example",
            fit=FitVerdict.GOOD,
            vertical_match=MatchVerdict.YES,
            geography_match=MatchVerdict.LIKELY,
            size_match=MatchVerdict.UNKNOWN,
            excluded=ExclusionVerdict.NO,
            reason="Relevant builder",
            reason_codes=[],
            evidence=["Candidate snippet"],
            inferred_vertical="construction",
            inferred_country="US",
            inferred_state="TX",
            inferred_employee_min=None,
            inferred_employee_max=None,
            inferred_ownership_type=None,
        )

    def close(self) -> None:
        pass


def test_query_planner_passes_normalized_spec_and_gap(spec: CompanySearchSpec) -> None:
    llm = CapturingLLM()
    spec = spec.model_copy(
        update={"external_search": ExternalSearchSpec(exa_searches=4, results_per_search=5)}
    )
    plan = QueryPlanner(llm, query_count=6).plan(spec, remaining_gap=12)
    assert len(plan.queries) == 4
    assert llm.prompts[0]["remaining_company_gap"] == 12
    assert llm.prompts[0]["required_query_count"] == 4
    assert llm.prompts[0]["search_spec"]["geography"]["states"] == ["TX"]


def test_evaluator_prevents_llm_identity_drift(spec: CompanySearchSpec) -> None:
    candidate = NormalizedCandidate(company_name="Acme", domain="acme.com", dedupe_key="acme.com")
    result = CandidateEvaluator(CapturingLLM()).evaluate(spec, candidate)
    assert result.company_name == "Acme"
    assert result.domain == "acme.com"


def test_evaluation_rejects_logically_inconsistent_good_fit() -> None:
    with pytest.raises(ValueError, match="good_fit"):
        CandidateEvaluation(
            company_name="Acme",
            domain="acme.com",
            fit=FitVerdict.GOOD,
            vertical_match=MatchVerdict.NO,
            geography_match=MatchVerdict.YES,
            size_match=MatchVerdict.YES,
            excluded=ExclusionVerdict.NO,
            reason="Contradictory",
            reason_codes=["vertical_mismatch"],
            evidence=[],
            inferred_vertical=None,
            inferred_country=None,
            inferred_state=None,
            inferred_employee_min=None,
            inferred_employee_max=None,
            inferred_ownership_type=None,
        )
