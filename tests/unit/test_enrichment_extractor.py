from __future__ import annotations

import json

from company_discovery.domain.models import EnrichmentExtraction, WebsitePage
from company_discovery.services.enrichment_extractor import EnrichmentExtractor


class FailingThenSuccessfulLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type):
        self.prompts.append(user_prompt)
        if len(self.prompts) == 1:
            raise ValueError("LLM returned invalid EnrichmentExtraction: truncated JSON")
        return EnrichmentExtraction(observed_company_name="Acme Builders")


def test_enrichment_extractor_retries_with_compact_page_text_after_failure() -> None:
    llm = FailingThenSuccessfulLLM()
    extractor = EnrichmentExtractor(llm)
    long_text = "A" * (EnrichmentExtractor.COMPACT_PAGE_TEXT_CHARS + 100)

    result = extractor.extract(
        {"company_name": "Acme Builders", "domain": "acme.com"},
        [WebsitePage(url="https://acme.com", text=long_text, page_type="homepage")],
    )

    assert result.observed_company_name == "Acme Builders"
    assert len(llm.prompts) == 2
    first_payload = json.loads(llm.prompts[0])
    second_payload = json.loads(llm.prompts[1])
    assert len(first_payload["sources"][0]["text"]) == len(long_text)
    assert len(second_payload["sources"][0]["text"]) == EnrichmentExtractor.COMPACT_PAGE_TEXT_CHARS
