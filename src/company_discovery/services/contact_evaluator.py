from __future__ import annotations

import json
from pathlib import Path

from company_discovery.adapters.protocols import StructuredLLM
from company_discovery.domain.contact_models import (
    ContactAssessment,
    ContactAssessmentBatch,
    ContactSearchBatch,
    ContactVerdict,
    EvidenceVerdict,
)


PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "contact_evaluation" / "system.md"


class ContactEvaluator:
    def __init__(self, llm: StructuredLLM) -> None:
        self._llm = llm
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def evaluate(
        self,
        batch: ContactSearchBatch,
        *,
        current_only: bool,
        require_role_match: bool,
    ) -> list[ContactAssessment]:
        payload = {
            "target": {
                "company_name": batch.company_name,
                "company_domain": batch.company_domain,
                "role_key": batch.role_key,
                "role_labels": batch.role_labels,
                "current_only": current_only,
                "require_role_match": require_role_match,
            },
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "text": result.text,
                    "published_date": result.published_date,
                }
                for result in batch.results
            ],
        }
        generated = self._llm.generate(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=True),
            response_model=ContactAssessmentBatch,
        )
        assert isinstance(generated, ContactAssessmentBatch)
        allowed_urls = {result.url for result in batch.results}
        candidates: list[ContactAssessment] = []
        for candidate in generated.candidates:
            valid_sources = [url for url in candidate.source_urls if url in allowed_urls]
            if not valid_sources:
                continue
            linkedin_url = candidate.linkedin_url
            if linkedin_url not in allowed_urls or "linkedin.com/in/" not in linkedin_url.lower():
                linkedin_url = next(
                    (
                        url
                        for url in valid_sources
                        if "linkedin.com/in/" in url.lower()
                    ),
                    None,
                )
            verdict = self._guard_verdict(
                candidate,
                current_only=current_only,
                require_role_match=require_role_match,
            )
            candidates.append(
                candidate.model_copy(
                    update={
                        "source_urls": valid_sources,
                        "linkedin_url": linkedin_url,
                        "verdict": verdict,
                    }
                )
            )
        return candidates

    @staticmethod
    def _guard_verdict(
        candidate: ContactAssessment,
        *,
        current_only: bool,
        require_role_match: bool,
    ) -> ContactVerdict:
        if (
            candidate.current_company_match == EvidenceVerdict.NO
            or candidate.role_match == EvidenceVerdict.NO
            or not candidate.identity_clear
        ):
            return ContactVerdict.REJECTED
        company_ok = candidate.current_company_match == EvidenceVerdict.YES or (
            not current_only and candidate.current_company_match == EvidenceVerdict.LIKELY
        )
        role_ok = candidate.role_match == EvidenceVerdict.YES or (
            not require_role_match and candidate.role_match == EvidenceVerdict.LIKELY
        )
        if company_ok and role_ok:
            return ContactVerdict.ACCEPTED
        return ContactVerdict.REVIEW

