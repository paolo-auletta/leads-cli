from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from company_discovery.domain.models import ExaSearchResult


class StructuredLLM(Protocol):
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel: ...

    def close(self) -> None: ...


class CompanySearchProvider(Protocol):
    @property
    def last_cost_dollars(self) -> float: ...

    def search(self, query: str, *, country: str, num_results: int) -> list[ExaSearchResult]: ...

    def close(self) -> None: ...
