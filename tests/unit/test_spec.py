from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from company_discovery.domain.spec import CompanySearchSpec, NoveltyMode


def test_national_vertical_without_size_or_exclusions_is_explicit(tmp_path) -> None:
    path = tmp_path / "company_search_spec.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "count": 50,
                "vertical": {"mode": "known", "key": "healthcare", "label": "Healthcare"},
                "geography": {"country": "us", "states": []},
            }
        )
    )

    spec = CompanySearchSpec.from_file(path)

    assert spec.count == 50
    assert spec.geography.country == "US"
    assert spec.company_size.is_unbounded
    assert spec.exclude.keywords == []
    assert spec.novelty_mode == NoveltyMode.UNUSED_MEMORY
    assert spec.missing_constraints == [
        "national search mode used",
        "no size filter applied",
        "no custom exclusions applied",
    ]


@pytest.mark.parametrize(
    ("legacy", "normalized"),
    [
        ("prefer_new", NoveltyMode.UNUSED_MEMORY),
        ("allow_known", NoveltyMode.FULL_MEMORY),
    ],
)
def test_legacy_novelty_modes_are_normalized(legacy, normalized) -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 5,
            "vertical": {"mode": "known", "key": "construction", "label": "Construction"},
            "novelty_mode": legacy,
        }
    )
    assert spec.novelty_mode == normalized


def test_exploratory_vertical_requires_seed_terms() -> None:
    with pytest.raises(ValidationError, match="seed term"):
        CompanySearchSpec.model_validate(
            {
                "version": 1,
                "count": 10,
                "vertical": {"mode": "exploratory", "key": "custom", "label": "Marine"},
            }
        )


@pytest.mark.parametrize(
    "override, message",
    [
        ({"geography": {"country": "US", "states": ["XX"]}}, "invalid US state"),
        ({"company_size": {"employee_min": 100, "employee_max": 10}}, "cannot exceed"),
        ({"unexpected": True}, "Extra inputs"),
    ],
)
def test_invalid_specs_are_rejected(override, message) -> None:
    payload = {
        "version": 1,
        "count": 10,
        "vertical": {"mode": "known", "key": "engineering", "label": "Engineering"},
        **override,
    }
    with pytest.raises(ValidationError, match=message):
        CompanySearchSpec.model_validate(payload)


def test_terms_and_states_are_normalized() -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 5,
            "vertical": {
                "mode": "exploratory",
                "key": "Marine-Surveying",
                "label": "Marine Surveying",
                "seed_terms": [" Vessel Inspection ", "vessel inspection"],
            },
            "geography": {"country": "us", "states": ["tx", "TX"]},
        }
    )
    assert spec.vertical.key == "marine-surveying"
    assert spec.vertical.seed_terms == ["vessel inspection"]
    assert spec.geography.states == ["TX"]


def test_multi_vertical_spec_has_equal_quotas_and_soft_balance_by_default() -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 8,
            "verticals": [
                {"mode": "known", "key": "construction", "label": "Construction"},
                {"mode": "known", "key": "healthcare", "label": "Healthcare"},
                {"mode": "known", "key": "engineering", "label": "Engineering"},
            ],
        }
    )

    assert [vertical.key for vertical in spec.verticals] == [
        "construction",
        "healthcare",
        "engineering",
    ]
    assert spec.vertical_quotas == {"construction": 3, "healthcare": 3, "engineering": 2}
    assert spec.balance_mode.value == "soft"
    assert "verticals" in spec.model_dump(mode="json")


def test_multi_vertical_keys_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="vertical keys must be unique"):
        CompanySearchSpec.model_validate(
            {
                "version": 1,
                "count": 10,
                "verticals": [
                    {"mode": "known", "key": "healthcare", "label": "Healthcare"},
                    {"mode": "known", "key": "healthcare", "label": "Health Care"},
                ],
            }
        )
