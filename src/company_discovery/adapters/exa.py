from __future__ import annotations

import time
from typing import Any

import httpx

from company_discovery.domain.models import ExaSearchResult
from company_discovery.settings import Settings


class ExaClient:
    """Minimal Exa company-search adapter that preserves each provider payload."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.exa_api_key:
            raise ValueError("EXA_API_KEY is required for external discovery")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.exa_base_url.rstrip("/"),
            headers={"x-api-key": settings.exa_api_key, "content-type": "application/json"},
            timeout=settings.exa_timeout_seconds,
        )
        self._last_cost_dollars = 0.0
        self._last_request_at: float | None = None

    @property
    def last_cost_dollars(self) -> float:
        return self._last_cost_dollars

    def search(self, query: str, *, country: str, num_results: int) -> list[ExaSearchResult]:
        payload = {
            "query": query,
            "numResults": max(1, min(num_results, 100)),
            "type": "auto",
            "category": "company",
            "userLocation": country.upper(),
            "contents": {"text": {"maxCharacters": 3000}},
            "systemPrompt": (
                "Return official operating-company websites. Avoid directories, associations, "
                "marketplaces, news pages, and duplicate companies."
            ),
        }
        response = self._post_with_retry(payload)
        data = response.json()
        self._last_cost_dollars = self._read_cost(data)
        return [
            ExaSearchResult(
                query=query,
                position=index,
                title=item.get("title") or "",
                url=item.get("url") or "",
                text=item.get("text"),
                published_date=item.get("publishedDate"),
                exa_id=item.get("id"),
                raw=item,
            )
            for index, item in enumerate(data.get("results", []), start=1)
        ]

    def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        for attempt in range(3):
            self._pace_request()
            response = self._client.post("/search", json=payload)
            self._last_request_at = time.monotonic()
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                return response
            if attempt == 2:
                response.raise_for_status()
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(delay)
        raise RuntimeError("Exa request retry loop exited unexpectedly")

    def _pace_request(self) -> None:
        if self._last_request_at is None:
            return
        remaining = 0.21 - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _read_cost(payload: dict[str, Any]) -> float:
        cost = payload.get("costDollars")
        if isinstance(cost, dict) and isinstance(cost.get("total"), (int, float)):
            return float(cost["total"])
        if isinstance(cost, (int, float)):
            return float(cost)
        return 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
