from __future__ import annotations

import json

from company_discovery.adapters.protocols import StructuredLLM
from company_discovery.domain.models import CandidateEvaluation, NormalizedCandidate
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.prompts import load_prompt


class CandidateEvaluator:
    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm
        self._system_prompt = load_prompt("candidate_evaluation")

    def evaluate(
        self,
        spec: CompanySearchSpec,
        candidate: NormalizedCandidate,
    ) -> CandidateEvaluation:
        prompt = json.dumps(
            {
                "search_spec": spec.model_dump(mode="json"),
                "candidate": candidate.model_dump(mode="json"),
            },
            indent=2,
        )
        result = self._llm.generate(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            response_model=CandidateEvaluation,
        )
        if not isinstance(result, CandidateEvaluation):
            raise TypeError(
                f"LLM returned {type(result).__name__}, expected CandidateEvaluation"
            )
        evaluation = result
        return evaluation.model_copy(
            update={"company_name": candidate.company_name, "domain": candidate.domain}
        )
