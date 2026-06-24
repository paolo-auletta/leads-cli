from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_schema(name: str) -> dict[str, object]:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_company_schema_tracks_runtime_vertical_aliases() -> None:
    schema = load_schema("company_search_spec.schema.json")
    vertical = schema["$defs"]["vertical"]  # type: ignore[index]
    properties = vertical["properties"]  # type: ignore[index]

    assert vertical["required"] == ["key", "label"]  # type: ignore[index]
    assert "search_terms" in properties
    assert "exclude_terms" in properties
    assert "mode" in properties
    assert "seed_terms" in properties
    assert "anti_terms" in properties
    assert {"not": {"required": ["search_terms", "seed_terms"]}} in vertical["allOf"]  # type: ignore[index]
    assert {"not": {"required": ["exclude_terms", "anti_terms"]}} in vertical["allOf"]  # type: ignore[index]


def test_company_schema_tracks_external_search_budget() -> None:
    schema = load_schema("company_search_spec.schema.json")
    external = schema["properties"]["external_search"]  # type: ignore[index]
    properties = external["properties"]  # type: ignore[index]

    assert properties["exa_searches"]["default"] == 8  # type: ignore[index]
    assert properties["exa_searches"]["minimum"] == 1  # type: ignore[index]
    assert properties["exa_searches"]["maximum"] == 20  # type: ignore[index]
    assert properties["results_per_search"]["default"] == 5  # type: ignore[index]
    assert properties["results_per_search"]["minimum"] == 1  # type: ignore[index]
    assert properties["results_per_search"]["maximum"] == 100  # type: ignore[index]


def test_contact_schema_tracks_runtime_role_key_normalization() -> None:
    schema = load_schema("contact_search_spec.schema.json")
    role = schema["properties"]["roles"]["items"]  # type: ignore[index]
    key = role["properties"]["key"]  # type: ignore[index]

    assert key["minLength"] == 2
    assert key["maxLength"] == 64
    assert key["pattern"] == "^[A-Za-z][A-Za-z0-9 _-]{1,63}$"
