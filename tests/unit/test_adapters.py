from __future__ import annotations

import json

import httpx

from company_discovery.adapters.exa import ExaClient
from company_discovery.adapters.llm import LiteLLMAdapter, build_llm
from company_discovery.adapters.website import WebsiteClient
from company_discovery.domain.models import CandidateEvaluation, EnrichmentExtraction, QueryPlan
from company_discovery.settings import Settings


def test_website_adapter_preserves_only_linkedin_company_profiles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
                <html><body><footer>
                  <a href="https://linkedin.com/company/acme-builders/?trk=footer">LinkedIn</a>
                  <a href="https://linkedin.com/in/acme-founder">Founder</a>
                  <a href="https://linkedin.com/jobs/view/123">Jobs</a>
                </footer></body></html>
            """,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    website = WebsiteClient(client=client, max_pages=1)

    pages = website.fetch("acme.com")

    assert pages[0].linkedin_urls == [
        "https://www.linkedin.com/company/acme-builders"
    ]


def test_exa_adapter_builds_company_search_and_preserves_raw_payload() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "costDollars": {"total": 0.01},
                "results": [{"id": "exa-1", "title": "Acme", "url": "https://acme.com", "text": "Builder"}],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://exa.test")
    adapter = ExaClient(Settings(exa_api_key="test"), client=client)
    results = adapter.search("Texas builders", country="US", num_results=25)
    assert captured["category"] == "company"
    assert captured["userLocation"] == "US"
    assert results[0].exa_id == "exa-1"
    assert results[0].raw["text"] == "Builder"
    assert adapter.last_cost_dollars == 0.01


def test_exa_adapter_separates_people_search_from_general_contact_evidence() -> None:
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://exa.test")
    adapter = ExaClient(Settings(exa_api_key="test"), client=client)

    adapter.search_people("project manager at Acme", country="US", num_results=10)
    adapter.search_contact_evidence("site:acme.com project manager", country="US", num_results=10)

    assert payloads[0]["category"] == "people"
    assert "category" not in payloads[1]


def test_llm_adapter_retries_invalid_structured_output() -> None:
    calls = 0
    payloads = []

    def completion(**kwargs):
        nonlocal calls
        calls += 1
        payloads.append(kwargs)
        content = '{"wrong": true}' if calls == 1 else json.dumps(
            {"queries": [f"query {index}" for index in range(6)], "rationale": "ok"}
        )
        return {"choices": [{"message": {"content": content}}]}

    adapter = LiteLLMAdapter(
        Settings(
            llm_provider="custom",
            llm_api_key="test",
            llm_base_url="https://llm.test",
            llm_model="gpt-5-mini",
            llm_response_format="auto",
        ),
        completion=completion,
    )
    result = adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert isinstance(result, QueryPlan)
    assert calls == 2
    assert payloads[0]["response_format"]["type"] == "json_object"
    assert "exact JSON Schema" in payloads[0]["messages"][0]["content"]
    assert payloads[0]["max_completion_tokens"] == 4096
    assert payloads[0]["drop_params"] is True
    assert payloads[0]["api_base"] == "https://llm.test"
    assert payloads[0]["model"] == "openai/gpt-5-mini"


def test_openai_uses_strict_json_schema_response_format() -> None:
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "queries": [f"query {index}" for index in range(6)],
                                "rationale": "ok",
                            }
                        )
                    }
                }
            ]
        }

    settings = Settings(
        llm_provider="openai",
        llm_api_key="test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-5-mini",
        llm_response_format="auto",
    )
    adapter = LiteLLMAdapter(settings, completion=completion)
    adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["max_completion_tokens"] == 4096
    assert captured["model"] == "gpt-5-mini"
    assert "api_base" not in captured
    assert "max_tokens" not in captured


def test_openai_strict_schema_requires_optional_fields_without_defaults() -> None:
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "company_name": "Acme",
                                "domain": "acme.com",
                                "fit": "good_fit",
                                "vertical_match": "yes",
                                "geography_match": "yes",
                                "size_match": "yes",
                                "excluded": "no",
                                "reason": "Matches the target profile.",
                                "reason_codes": ["vertical_match"],
                                "evidence": ["Acme says it serves construction companies."],
                                "inferred_vertical": "construction",
                                "inferred_country": "US",
                                "inferred_state": None,
                                "inferred_employee_min": 25,
                                "inferred_employee_max": 100,
                                "inferred_ownership_type": None,
                                "target_vertical": None,
                            }
                        )
                    }
                }
            ]
        }

    adapter = LiteLLMAdapter(
        Settings(
            llm_provider="openai",
            llm_api_key="test",
            llm_model="gpt-5-mini",
            llm_response_format="auto",
        ),
        completion=completion,
    )
    adapter.generate(system_prompt="system", user_prompt="user", response_model=CandidateEvaluation)

    schema = captured["response_format"]["json_schema"]["schema"]
    properties = schema["properties"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(properties.keys())
    assert "target_vertical" in schema["required"]
    assert "default" not in properties["target_vertical"]


def test_openai_strict_schema_normalizes_nested_definitions() -> None:
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "observed_company_name": None,
                                "identity_conflict": False,
                                "identity_conflict_reason": None,
                                "phones": [],
                                "locations": [],
                                "ownership_signals": [],
                                "linkedin_profiles": [],
                            }
                        )
                    }
                }
            ]
        }

    adapter = LiteLLMAdapter(
        Settings(
            llm_provider="openai",
            llm_api_key="test",
            llm_model="gpt-5-mini",
            llm_response_format="auto",
        ),
        completion=completion,
    )
    adapter.generate(system_prompt="system", user_prompt="user", response_model=EnrichmentExtraction)

    schema = captured["response_format"]["json_schema"]["schema"]
    assert schema["required"] == list(schema["properties"].keys())
    assert "default" not in schema["properties"]["observed_company_name"]
    assert schema["$defs"]["PhoneObservation"]["additionalProperties"] is False
    assert schema["$defs"]["PhoneObservation"]["required"] == list(
        schema["$defs"]["PhoneObservation"]["properties"].keys()
    )


def test_deepseek_uses_json_object_response_format() -> None:
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "queries": [f"query {index}" for index in range(6)],
                                "rationale": "ok",
                            }
                        )
                    }
                }
            ]
        }

    settings = Settings(
        llm_api_key="test",
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-chat",
    )
    adapter = LiteLLMAdapter(settings, completion=completion)
    adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert captured["response_format"] == {"type": "json_object"}
    assert "Return JSON only" in captured["messages"][0]["content"]
    assert captured["max_completion_tokens"] == 4096
    assert captured["model"] == "deepseek/deepseek-chat"


def test_llm_factory_uses_litellm_adapter_for_all_providers() -> None:
    assert isinstance(build_llm(Settings(llm_provider="anthropic", llm_api_key="test")), LiteLLMAdapter)
    assert isinstance(build_llm(Settings(llm_provider="google-gemini", llm_api_key="test")), LiteLLMAdapter)
    assert isinstance(build_llm(Settings(llm_provider="openai", llm_api_key="test")), LiteLLMAdapter)


def test_litellm_adapter_prefixes_native_provider_models() -> None:
    cases = [
        ("anthropic", "claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
        ("google-gemini", "gemini-3.5-flash", "gemini/gemini-3.5-flash"),
        ("deepseek", "deepseek-chat", "deepseek/deepseek-chat"),
        ("openai", "gpt-5-mini", "gpt-5-mini"),
        ("custom", "local-model", "openai/local-model"),
        ("custom", "openrouter/qwen/qwen3", "openrouter/qwen/qwen3"),
    ]

    for provider, model, expected in cases:
        captured = {}

        def completion(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "queries": [f"query {index}" for index in range(6)],
                                    "rationale": "ok",
                                }
                            )
                        }
                    }
                ]
            }

        adapter = LiteLLMAdapter(
            Settings(llm_provider=provider, llm_model=model, llm_api_key="test"),
            completion=completion,
        )
        adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)

        assert captured["model"] == expected


def test_official_litellm_providers_default_to_json_schema() -> None:
    for provider in ["openai", "anthropic", "google-gemini", "gemini"]:
        assert Settings(llm_provider=provider, llm_response_format="auto").resolved_llm_response_format == "json_schema"

    assert Settings(llm_provider="deepseek", llm_response_format="auto").resolved_llm_response_format == "json_object"
    assert (
        Settings(
            llm_provider="custom",
            llm_base_url="https://llm.test",
            llm_response_format="auto",
        ).resolved_llm_response_format
        == "json_object"
    )


def test_llm_adapter_surfaces_model_refusal() -> None:
    def completion(**kwargs):
        return {"choices": [{"message": {"content": None, "refusal": "cannot comply"}}]}

    adapter = LiteLLMAdapter(Settings(llm_api_key="test"), completion=completion)
    import pytest

    with pytest.raises(ValueError, match="refused"):
        adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
