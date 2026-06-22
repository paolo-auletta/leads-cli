from __future__ import annotations

import json

from company_discovery.adapters.protocols import StructuredLLM
from company_discovery.domain.models import QueryPlan
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.prompts import load_prompt


class QueryPlanner:
    def __init__(self, llm: StructuredLLM, query_count: int = 8) -> None:
        if not 6 <= query_count <= 12:
            raise ValueError("query_count must be between 6 and 12")
        self._llm = llm
        self._query_count = query_count
        self._system_prompt = load_prompt("query_generation")

    def plan(self, spec: CompanySearchSpec, remaining_gap: int) -> QueryPlan:
        prompt = json.dumps(
            {
                "search_spec": spec.model_dump(mode="json"),
                "remaining_company_gap": remaining_gap,
                "required_query_count": self._query_count,
            },
            indent=2,
        )
        result = self._llm.generate(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            response_model=QueryPlan,
        )
        if not isinstance(result, QueryPlan):
            raise TypeError(f"LLM returned {type(result).__name__}, expected QueryPlan")
        plan = result
        queries = list(dict.fromkeys(query.strip() for query in plan.queries if query.strip()))
        if len(queries) < 6:
            raise ValueError("LLM query plan must contain at least 6 unique queries")
        return plan.model_copy(update={"queries": queries[:12]})
