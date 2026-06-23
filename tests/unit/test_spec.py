from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from company_discovery.domain.spec import CompanySearchSpec, NoveltyMode, OwnershipSignalKind


def test_national_vertical_without_size_or_exclusions_is_explicit(tmp_path) -> None:
    path = tmp_path / "company_search_spec.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "count": 50,
                "vertical": {"key": "healthcare", "label": "Healthcare"},
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
            "vertical": {"key": "construction", "label": "Construction"},
            "novelty_mode": legacy,
        }
    )
    assert spec.novelty_mode == normalized


def test_reserve_count_uses_predictable_ceiling_policy() -> None:
    one = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 1,
            "vertical": {"key": "construction", "label": "Construction"},
            "reserve_ratio": 0.5,
        }
    )
    three = one.model_copy(update={"count": 3})
    disabled = one.model_copy(update={"reserve_ratio": 0})

    assert one.reserve_count == 1
    assert three.reserve_count == 2
    assert disabled.reserve_count == 0


def test_legacy_vertical_fields_are_normalized() -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 10,
            "vertical": {
                "mode": "exploratory",
                "key": "custom",
                "label": "Marine",
                "seed_terms": [" Vessel Inspection ", "vessel inspection"],
                "anti_terms": [" Directory ", "directory"],
            },
        }
    )

    assert spec.vertical.key == "custom"
    assert spec.vertical.search_terms == ["vessel inspection"]
    assert spec.vertical.exclude_terms == ["directory"]
    assert "mode" not in spec.model_dump(mode="json")["verticals"][0]


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
        "vertical": {"key": "engineering", "label": "Engineering"},
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
                "key": "Marine-Surveying",
                "label": "Marine Surveying",
                "search_terms": [" Vessel Inspection ", "vessel inspection"],
            },
            "geography": {"country": "us", "states": ["tx", "TX"]},
        }
    )
    assert spec.vertical.key == "marine-surveying"
    assert spec.vertical.search_terms == ["vessel inspection"]
    assert spec.geography.states == ["TX"]


def test_structured_ownership_exclusions_are_normalized() -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 5,
            "vertical": {"key": "construction", "label": "Construction"},
            "exclude": {
                "structured": {"ownership_signals": [" FAMILY_OWNED ", "family_owned"]}
            },
        }
    )

    assert spec.exclude.structured.ownership_signals == [OwnershipSignalKind.FAMILY_OWNED]
    assert "no custom exclusions applied" not in spec.missing_constraints


def test_multi_vertical_spec_has_equal_quotas_and_soft_balance_by_default() -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 8,
            "verticals": [
                {"key": "construction", "label": "Construction"},
                {"key": "healthcare", "label": "Healthcare"},
                {"key": "engineering", "label": "Engineering"},
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
                    {"key": "healthcare", "label": "Healthcare"},
                    {"key": "healthcare", "label": "Health Care"},
                ],
            }
        )
