from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from company_discovery.settings import Settings


def build_llm(settings: Settings) -> OpenAICompatibleLLM | AnthropicLLM | GeminiLLM:
    provider = settings.llm_provider.strip().lower()
    if provider == "anthropic":
        return AnthropicLLM(settings)
    if provider in {"google-gemini", "gemini"}:
        return GeminiLLM(settings)
    return OpenAICompatibleLLM(settings)


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


class AnthropicLLM:
    """Structured-output client for Anthropic's Messages API."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required for query generation and evaluation")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.llm_base_url.rstrip("/"),
            headers={
                "x-api-key": settings.llm_api_key,
                "anthropic-version": "2023-06-01",
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
        messages = [{"role": "user", "content": user_prompt}]
        schema = _provider_json_schema(response_model)
        for attempt in range(2):
            payload = {
                "model": self._settings.llm_model,
                "max_tokens": self._settings.llm_max_tokens,
                "system": system_prompt,
                "messages": messages,
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": schema,
                    }
                },
            }
            response = _post_with_retry(
                self._client,
                "/messages",
                payload,
                api_name="LLM API",
            )
            content = _anthropic_text(response.json())
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

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class GeminiLLM:
    """Structured-output client for Google's Gemini Interactions API."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required for query generation and evaluation")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.llm_base_url.rstrip("/"),
            headers={
                "x-goog-api-key": settings.llm_api_key,
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
        prompt = f"{system_prompt}\n\n{user_prompt}"
        schema = _provider_json_schema(response_model)
        for attempt in range(2):
            payload = {
                "model": self._settings.llm_model,
                "input": prompt,
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
            }
            response = _post_with_retry(
                self._client,
                "/interactions",
                payload,
                api_name="LLM API",
            )
            content = _gemini_text(response.json())
            try:
                return response_model.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise ValueError(f"LLM returned invalid {response_model.__name__}: {exc}") from exc
                prompt = (
                    f"{system_prompt}\n\n{user_prompt}\n\n"
                    "The previous response did not satisfy the JSON Schema. "
                    f"Validation error: {exc}. Return JSON only."
                )
        raise RuntimeError("structured generation exhausted retries")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _post_with_retry(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
    *,
    api_name: str,
) -> httpx.Response:
    for attempt in range(3):
        try:
            response = client.post(path, json=payload)
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code != 429 and response.status_code < 500:
            if response.is_error:
                detail = response.text.strip()[:1000]
                raise ValueError(
                    f"{api_name} returned HTTP {response.status_code}: {detail or 'no error body'}"
                )
            return response
        if attempt == 2:
            response.raise_for_status()
        retry_after = response.headers.get("retry-after")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        time.sleep(delay)
    raise RuntimeError("LLM request retry loop exited unexpectedly")


def _anthropic_text(payload: dict[str, Any]) -> str:
    parts = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _gemini_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts = []
    for item in payload.get("output", []):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def _provider_json_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    schema = deepcopy(response_model.model_json_schema())
    _normalize_provider_schema(schema)
    return schema


def _normalize_provider_schema(value: Any) -> None:
    if isinstance(value, dict):
        any_of = value.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            non_null = [item for item in any_of if item != {"type": "null"}]
            has_null = len(non_null) == 1 and any(item == {"type": "null"} for item in any_of)
            if has_null and isinstance(non_null[0], dict) and "type" in non_null[0]:
                replacement = dict(non_null[0])
                item_type = replacement.get("type")
                if isinstance(item_type, str):
                    replacement["type"] = [item_type, "null"]
                    value.pop("anyOf")
                    value.update(replacement)
        if value.get("type") == "object":
            value.setdefault("additionalProperties", False)
        for child in value.values():
            _normalize_provider_schema(child)
    elif isinstance(value, list):
        for child in value:
            _normalize_provider_schema(child)
