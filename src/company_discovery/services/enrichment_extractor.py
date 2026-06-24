from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from company_discovery.domain.models import EnrichmentExtraction, WebsitePage


class StructuredGenerator(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type): ...


class EnrichmentExtractor:
    COMPACT_PAGE_TEXT_CHARS = 6000

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
        try:
            return self._extract(discovery, pages)
        except Exception as exc:
            compact_pages = self._compact_pages(pages)
            try:
                return self._extract(discovery, compact_pages)
            except Exception as retry_exc:
                raise ValueError(
                    "LLM enrichment extraction failed after compact retry: "
                    f"initial error: {exc}; retry error: {retry_exc}"
                ) from retry_exc

    def _extract(
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

    @classmethod
    def _compact_pages(cls, pages: list[WebsitePage]) -> list[WebsitePage]:
        return [
            page.model_copy(update={"text": page.text[: cls.COMPACT_PAGE_TEXT_CHARS]})
            for page in pages
        ]
