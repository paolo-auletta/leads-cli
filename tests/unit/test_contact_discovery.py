from __future__ import annotations

import json

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
                "company_source": {"enrichment_run_id": "company-enrich-a1b2c3d4e5f6"},
                "roles": [
                    {"key": "manager", "labels": ["general manager"]},
                    {"key": "manager", "labels": ["operations manager"]},
                ],
            }
        )


def test_contact_role_keys_normalize_human_labels() -> None:
    spec = ContactSearchSpec.model_validate(
        {
            "company_source": {"enrichment_run_id": "company-enrich-a1b2c3d4e5f6"},
            "roles": [{"key": "Project Manager", "labels": ["Project Manager"]}],
        }
    )

    assert spec.roles[0].key == "project_manager"


def test_contact_spec_missing_file_uses_clean_value_error(tmp_path) -> None:
    missing = tmp_path / "missing_contact_spec.json"

    with pytest.raises(ValueError, match="spec file does not exist"):
        ContactSearchSpec.from_file(missing)


def test_contact_spec_invalid_json_uses_clean_value_error(tmp_path) -> None:
    bad = tmp_path / "bad_contact_spec.json"
    bad.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        ContactSearchSpec.from_file(bad)


def test_contact_spec_from_file_normalizes_role_key(tmp_path) -> None:
    path = tmp_path / "contact_search_spec.json"
    path.write_text(
        json.dumps(
            {
                "company_source": {"enrichment_run_id": "company-enrich-a1b2c3d4e5f6"},
                "roles": [{"key": "Project Manager", "labels": ["Project Manager"]}],
            }
        ),
        encoding="utf-8",
    )

    assert ContactSearchSpec.from_file(path).roles[0].key == "project_manager"
