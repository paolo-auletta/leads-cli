from __future__ import annotations

import json
import time

import httpx
from pydantic import BaseModel, ValidationError

from company_discovery.settings import Settings


class OpenAICompatibleLLM:
    """Structured-output client for OpenAI-compatible chat completion APIs."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required for query generation and evaluation")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.llm_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.llm_timeout_seconds,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        schema = response_model.model_json_schema()
        response_format = self._response_format(response_model, schema)
        if self._settings.resolved_llm_response_format == "json_object":
            messages[0]["content"] = (
                f"{system_prompt}\n\n"
                "Return JSON only. The JSON must match this exact JSON Schema:\n"
                f"{json.dumps(schema, ensure_ascii=True)}"
            )
        for attempt in range(2):
            payload = {
                "model": self._settings.llm_model,
                "messages": messages,
                "max_tokens": self._settings.llm_max_tokens,
                "response_format": response_format,
            }
            response = self._post_with_retry(payload)
            message = response.json()["choices"][0]["message"]
            if message.get("refusal"):
                raise ValueError(f"LLM refused structured generation: {message['refusal']}")
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = ""
            try:
                return response_model.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise ValueError(f"LLM returned invalid {response_model.__name__}: {exc}") from exc
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Correct the response to satisfy the supplied JSON Schema. "
                                f"Validation error: {exc}. Return JSON only."
                            ),
                        },
                    ]
                )
        raise RuntimeError("structured generation exhausted retries")

    def _response_format(self, response_model: type[BaseModel], schema: dict) -> dict:
        if self._settings.resolved_llm_response_format == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__.lower(),
                "strict": True,
                "schema": schema,
            },
        }

    def _post_with_retry(self, payload: dict) -> httpx.Response:
        for attempt in range(3):
            try:
                response = self._client.post("/chat/completions", json=payload)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
                continue
            if response.status_code != 429 and response.status_code < 500:
                if response.is_error:
                    detail = response.text.strip()[:1000]
                    raise ValueError(
                        f"LLM API returned HTTP {response.status_code}: {detail or 'no error body'}"
                    )
                return response
            if attempt == 2:
                response.raise_for_status()
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(delay)
        raise RuntimeError("LLM request retry loop exited unexpectedly")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
