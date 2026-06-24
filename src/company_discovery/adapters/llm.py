from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from company_discovery.settings import Settings


CompletionCallable = Callable[..., Any]


def build_llm(settings: Settings) -> LiteLLMAdapter:
    return LiteLLMAdapter(settings)


class LiteLLMAdapter:
    """Structured-output LLM client backed by LiteLLM provider normalization."""

    def __init__(self, settings: Settings, completion: CompletionCallable | None = None) -> None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required for query generation and evaluation")
        self._settings = settings
        self._completion = completion or _litellm_completion

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        schema = response_model.model_json_schema()
        response_format = self._response_format(response_model, schema)
        if response_format["type"] == "json_object":
            messages[0]["content"] = (
                f"{system_prompt}\n\n"
                "Return JSON only. The JSON must match this exact JSON Schema:\n"
                f"{json.dumps(schema, ensure_ascii=True)}"
            )

        for attempt in range(2):
            content = self._complete(messages=messages, response_format=response_format)
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

    def _complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any],
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._litellm_model(),
            "messages": messages,
            "api_key": self._settings.llm_api_key,
            "timeout": self._settings.llm_timeout_seconds,
            "num_retries": 2,
            "drop_params": True,
            "response_format": response_format,
            "max_completion_tokens": self._settings.llm_max_tokens,
        }
        api_base = self._litellm_api_base()
        if api_base:
            kwargs["api_base"] = api_base

        try:
            response = self._completion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - provider SDKs expose heterogeneous exceptions.
            raise ValueError(f"LLM API request failed: {exc}") from exc

        message = _first_message(response)
        if message.get("refusal"):
            raise ValueError(f"LLM refused structured generation: {message['refusal']}")
        content = message.get("content") or ""
        if isinstance(content, list):
            return _text_from_content_blocks(content)
        if isinstance(content, str):
            return content
        return ""

    def _response_format(self, response_model: type[BaseModel], schema: dict[str, Any]) -> dict[str, Any]:
        if self._settings.resolved_llm_response_format == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__.lower(),
                "strict": True,
                "schema": _openai_strict_schema(schema),
            },
        }

    def _litellm_model(self) -> str:
        model = self._settings.llm_model.strip()
        provider = self._settings.llm_provider.strip().lower()
        if "/" in model:
            return model
        if provider in {"deepseek"}:
            return f"deepseek/{model}"
        if provider in {"anthropic"}:
            return f"anthropic/{model}"
        if provider in {"google-gemini", "gemini"}:
            return f"gemini/{model}"
        if provider in {"custom", "openai-compatible"}:
            return f"openai/{model}"
        return model

    def _litellm_api_base(self) -> str | None:
        provider = self._settings.llm_provider.strip().lower()
        if provider in {"custom", "openai-compatible"}:
            return self._settings.llm_base_url.rstrip("/")
        return None

    def close(self) -> None:
        return None


class OpenAICompatibleLLM(LiteLLMAdapter):
    """Backward-compatible name for the LiteLLM-backed OpenAI-compatible adapter."""


class AnthropicLLM(LiteLLMAdapter):
    """Backward-compatible name for the LiteLLM-backed Anthropic adapter."""


class GeminiLLM(LiteLLMAdapter):
    """Backward-compatible name for the LiteLLM-backed Gemini adapter."""


def _litellm_completion(**kwargs: Any) -> Any:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    try:
        from litellm import completion
    except ImportError as exc:  # pragma: no cover - guarded by package dependencies.
        raise RuntimeError("The 'litellm' package is required for LLM providers") from exc
    return completion(**kwargs)


def _openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    strict_schema = deepcopy(schema)
    _normalize_openai_strict_schema(strict_schema)
    return strict_schema


def _normalize_openai_strict_schema(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        properties = value.get("properties")
        if isinstance(properties, dict):
            value["additionalProperties"] = False
            value["required"] = list(properties.keys())
        for child in value.values():
            _normalize_openai_strict_schema(child)
    elif isinstance(value, list):
        for child in value:
            _normalize_openai_strict_schema(child)


def _first_message(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        return message if isinstance(message, dict) else {}

    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        if isinstance(message, dict):
            return message
        if message is not None:
            content = getattr(message, "content", None)
            refusal = getattr(message, "refusal", None)
            return {"content": content, "refusal": refusal}
    return {}


def _text_from_content_blocks(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)
