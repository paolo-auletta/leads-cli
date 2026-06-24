from __future__ import annotations

import json

import httpx

from company_discovery.adapters.exa import ExaClient
from company_discovery.adapters.llm import AnthropicLLM, GeminiLLM, OpenAICompatibleLLM, build_llm
from company_discovery.adapters.website import WebsiteClient
from company_discovery.domain.models import QueryPlan
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

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payloads.append(json.loads(request.content))
        content = '{"wrong": true}' if calls == 1 else json.dumps(
            {"queries": [f"query {index}" for index in range(6)], "rationale": "ok"}
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test")
    adapter = OpenAICompatibleLLM(
        Settings(llm_api_key="test", llm_base_url="https://llm.test"),
        client=client,
    )
    result = adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert isinstance(result, QueryPlan)
    assert calls == 2
    assert payloads[0]["response_format"]["type"] == "json_object"
    assert "exact JSON Schema" in payloads[0]["messages"][0]["content"]
    assert payloads[0]["max_tokens"] == 4096


def test_openai_uses_strict_json_schema_response_format() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
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
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://openai.test")
    settings = Settings(
        llm_api_key="test",
        llm_base_url="https://api.openai.com/v1",
        llm_response_format="auto",
    )
    adapter = OpenAICompatibleLLM(settings, client=client)
    adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True


def test_deepseek_uses_json_object_response_format() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
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
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://deepseek.test")
    settings = Settings(
        llm_api_key="test",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-chat",
    )
    adapter = OpenAICompatibleLLM(settings, client=client)
    adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
    assert captured["response_format"] == {"type": "json_object"}
    assert "Return JSON only" in captured["messages"][0]["content"]


def test_llm_factory_selects_native_provider_adapters() -> None:
    assert isinstance(
        build_llm(Settings(llm_provider="anthropic", llm_api_key="test")),
        AnthropicLLM,
    )
    assert isinstance(
        build_llm(Settings(llm_provider="google-gemini", llm_api_key="test")),
        GeminiLLM,
    )
    assert isinstance(
        build_llm(Settings(llm_provider="openai", llm_api_key="test")),
        OpenAICompatibleLLM,
    )


def test_anthropic_adapter_uses_messages_structured_outputs() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "queries": [f"query {index}" for index in range(6)],
                                "rationale": "ok",
                            }
                        ),
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://anthropic.test")
    adapter = AnthropicLLM(
        Settings(
            llm_provider="anthropic",
            llm_api_key="test",
            llm_base_url="https://api.anthropic.com/v1",
            llm_model="claude-sonnet-4-6",
        ),
        client=client,
    )

    result = adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)

    assert isinstance(result, QueryPlan)
    assert captured["path"] == "/messages"
    body = captured["body"]
    assert body["model"] == "claude-sonnet-4-6"
    assert body["system"] == "system"
    assert body["messages"] == [{"role": "user", "content": "user"}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["type"] == "object"


def test_gemini_adapter_uses_interactions_structured_outputs() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "queries": [f"query {index}" for index in range(6)],
                        "rationale": "ok",
                    }
                )
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://gemini.test")
    adapter = GeminiLLM(
        Settings(
            llm_provider="google-gemini",
            llm_api_key="test",
            llm_base_url="https://generativelanguage.googleapis.com/v1beta",
            llm_model="gemini-3.5-flash",
        ),
        client=client,
    )

    result = adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)

    assert isinstance(result, QueryPlan)
    assert captured["path"] == "/interactions"
    body = captured["body"]
    assert body["model"] == "gemini-3.5-flash"
    assert body["input"] == "system\n\nuser"
    assert body["response_format"]["type"] == "text"
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["type"] == "object"


def test_llm_adapter_surfaces_model_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": None, "refusal": "cannot comply"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llm.test")
    adapter = OpenAICompatibleLLM(Settings(llm_api_key="test"), client=client)
    import pytest

    with pytest.raises(ValueError, match="refused"):
        adapter.generate(system_prompt="system", user_prompt="user", response_model=QueryPlan)
