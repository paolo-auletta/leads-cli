from __future__ import annotations

import pytest
from pydantic import ValidationError

from company_discovery.domain.contact_models import (
    ContactAssessmentBatch,
    ContactSearchBatch,
    ContactVerdict,
)
from company_discovery.domain.contact_spec import ContactSearchSpec
from company_discovery.domain.models import ExaSearchResult
from company_discovery.services.contact_evaluator import ContactEvaluator


class FakeLLM:
    def generate(self, **_: object) -> ContactAssessmentBatch:
        return ContactAssessmentBatch.model_validate(
            {
                "candidates": [
                    {
                        "full_name": "Jane Smith",
                        "title": "Project Manager",
                        "linkedin_url": "https://invented.example/jane",
                        "source_urls": [
                            "https://www.linkedin.com/in/jane-smith",
                            "https://invented.example/jane",
                        ],
                        "evidence": ["Project Manager at Acme Builders"],
                        "current_company_match": "likely",
                        "role_match": "yes",
                        "identity_clear": True,
                        "verdict": "accepted",
                        "reason": "The role matches but employment is not explicit.",
                    }
                ]
            }
        )


def test_contact_evaluator_downgrades_weak_employment_and_removes_invented_urls() -> None:
    evaluator = ContactEvaluator(FakeLLM())  # type: ignore[arg-type]
    results = evaluator.evaluate(
        ContactSearchBatch(
            company_name="Acme Builders",
            company_domain="acme.com",
            role_key="project_manager",
            role_labels=["project manager"],
            results=[
                ExaSearchResult(
                    query="query",
                    position=1,
                    title="Jane Smith",
                    url="https://www.linkedin.com/in/jane-smith",
                )
            ],
        ),
        current_only=True,
        require_role_match=True,
    )

    assert results[0].verdict == ContactVerdict.REVIEW
    assert results[0].linkedin_url == "https://www.linkedin.com/in/jane-smith"
    assert results[0].source_urls == ["https://www.linkedin.com/in/jane-smith"]


def test_contact_spec_requires_distinct_role_keys() -> None:
    with pytest.raises(ValidationError, match="role keys must be unique"):
        ContactSearchSpec.model_validate(
            {
                "company_source": {"enrichment_run_id": "enrichment-run-1"},
                "roles": [
                    {"key": "manager", "labels": ["general manager"]},
                    {"key": "manager", "labels": ["operations manager"]},
                ],
            }
        )
