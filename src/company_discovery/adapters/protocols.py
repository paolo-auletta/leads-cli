from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from company_discovery.domain.contact_models import ApolloBatchResult, ApolloPersonRequest
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


class ContactSearchProvider(Protocol):
    @property
    def last_cost_dollars(self) -> float: ...

    def search_people(
        self, query: str, *, country: str, num_results: int
    ) -> list[ExaSearchResult]: ...

    def search_contact_evidence(
        self, query: str, *, country: str, num_results: int
    ) -> list[ExaSearchResult]: ...

    def close(self) -> None: ...


class ContactEnrichmentProvider(Protocol):
    def enrich_people(
        self,
        people: list[ApolloPersonRequest],
        *,
        reveal_email: bool,
        reveal_phone: bool,
    ) -> ApolloBatchResult: ...

    def poll(self, request_id: str) -> ApolloBatchResult: ...

    def close(self) -> None: ...
