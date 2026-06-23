from __future__ import annotations

import json

import httpx

from company_discovery.adapters.apollo import ApolloClient
from company_discovery.domain.contact_models import ApolloPersonRequest
from company_discovery.settings import Settings


def _request() -> ApolloPersonRequest:
    return ApolloPersonRequest(
        candidate_id=7,
        first_name="Jane",
        last_name="Smith",
        full_name="Jane Smith",
        company_name="Acme Builders",
        company_domain="acme.com",
        linkedin_url="https://www.linkedin.com/in/jane-smith",
    )


def test_apollo_bulk_match_sends_strong_identifiers_and_parses_channels() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "person": {
                            "id": "apollo-1",
                            "name": "Jane Smith",
                            "title": "Project Manager",
                            "linkedin_url": "https://www.linkedin.com/in/jane-smith",
                            "email": "jane@acme.com",
                            "email_status": "verified",
                            "phone_numbers": [{"sanitized_number": "+15125550100"}],
                            "organization": {
                                "name": "Acme Builders",
                                "primary_domain": "acme.com",
                            },
                        }
                    }
                ]
            },
        )

    settings = Settings(
        apollo_api_key="test-key",
        apollo_webhook_url="https://example.test/apollo-webhook",
    )
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.apollo.io"
    )
    adapter = ApolloClient(settings, client=client)

    result = adapter.enrich_people([_request()], reveal_email=True, reveal_phone=True)

    assert captured["path"] == "/api/v1/people/bulk_match"
    assert '"linkedin_url":"https://www.linkedin.com/in/jane-smith"' in str(captured["body"])
    assert result.pending is False
    assert result.matches[0].candidate_id == 7
    assert result.matches[0].email == "jane@acme.com"
    assert result.matches[0].phones == ["+15125550100"]
    assert result.matches[0].organization_domain == "acme.com"


def test_apollo_phone_enrichment_requires_webhook() -> None:
    settings = Settings(apollo_api_key="test-key", apollo_webhook_url="")
    adapter = ApolloClient(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
            base_url="https://api.apollo.io",
        ),
    )

    try:
        adapter.enrich_people([_request()], reveal_email=True, reveal_phone=True)
    except ValueError as exc:
        assert "APOLLO_WEBHOOK_URL" in str(exc)
    else:
        raise AssertionError("phone enrichment must require a webhook URL")


def test_apollo_email_only_uses_synchronous_work_email_without_waterfall() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"matches": [{"person": {"name": "Jane Smith", "email": "jane@acme.com"}}]},
        )

    adapter = ApolloClient(
        Settings(apollo_api_key="test-key", apollo_webhook_url=""),
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.apollo.io"
        ),
    )

    result = adapter.enrich_people([_request()], reveal_email=True, reveal_phone=False)

    assert captured["run_waterfall_email"] is False
    assert captured["reveal_phone_number"] is False
    assert result.matches[0].email == "jane@acme.com"


def test_apollo_async_result_can_be_polled() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-1", "status": "pending"})
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "status": "completed",
                "matches": [{"person": {"name": "Jane Smith", "email": "jane@acme.com"}}],
            },
        )

    settings = Settings(
        apollo_api_key="test-key",
        apollo_webhook_url="https://example.test/apollo-webhook",
    )
    adapter = ApolloClient(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.apollo.io"
        ),
    )

    submitted = adapter.enrich_people([_request()], reveal_email=True, reveal_phone=True)
    completed = adapter.poll("req-1")

    assert submitted.pending is True
    assert completed.pending is False
    assert completed.matches[0].candidate_id == 7
    assert completed.matches[0].email == "jane@acme.com"
    assert calls == 2
