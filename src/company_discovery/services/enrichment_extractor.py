from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from company_discovery.domain.models import EnrichmentExtraction, WebsitePage


class StructuredGenerator(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type): ...


class EnrichmentExtractor:
    def __init__(self, llm: StructuredGenerator) -> None:
        self._llm = llm
        self._system_prompt = (
            Path(__file__).parents[1] / "prompts" / "company_enrichment" / "system.md"
        ).read_text(encoding="utf-8")

    def extract(
        self,
        discovery: dict[str, object],
        pages: list[WebsitePage],
    ) -> EnrichmentExtraction:
        payload = {
            "known_company": discovery,
            "sources": [page.model_dump(mode="json") for page in pages],
        }
        result = self._llm.generate(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=True),
            response_model=EnrichmentExtraction,
        )
        return EnrichmentExtraction.model_validate(result)
