"""Provider HTTP adapters. Sampling knobs are not treated as interchangeable."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from rewardbench.providers.http import (
    HttpRequest,
    Transport,
    TransportError,
    UrllibTransport,
    dump_json,
    read_json_object,
    status_error,
)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_ROOT = "https://generativelanguage.googleapis.com/v1beta"
XAI_URL = "https://api.x.ai/v1/chat/completions"
ANTHROPIC_VERSION = "2023-06-01"

_KEY_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "xai": ("XAI_API_KEY",),
}


@dataclass(frozen=True)
class Completion:
    text: str
    response_model_id: str | None
    request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_seconds: float
    finish_reason: str | None
    extra_usage: dict[str, Any]
    applied_settings: dict[str, Any]
    ignored_settings: dict[str, str]


@dataclass(frozen=True)
class ScriptedReply:
    text: str
    prompt_tokens: int = 12
    completion_tokens: int = 30
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    response_model_id: str | None = None
    request_id: str | None = "mock-req"
    finish_reason: str = "stop"


class MockBackend:
    """Offline adapter. ``script`` items are text, :class:`ScriptedReply`, or errors."""

    provider_name = "mock"

    def __init__(self, script: Sequence[object] | None = None) -> None:
        self.script: list[object] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model_id: str,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> Completion:
        self.calls.append(
            {
                "model_id": model_id,
                "system": system_text,
                "user": user_text,
                "settings": dict(settings),
            }
        )
        item: object
        if self.script:
            item = self.script.pop(0)
        else:
            item = ScriptedReply(text='{"policy":"heuristic"}')
        if isinstance(item, Exception):
            raise item
        reply = item if isinstance(item, ScriptedReply) else ScriptedReply(text=str(item))
        total = reply.total_tokens or reply.prompt_tokens + reply.completion_tokens
        return Completion(
            text=reply.text,
            response_model_id=reply.response_model_id or model_id,
            request_id=reply.request_id,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            reasoning_tokens=reply.reasoning_tokens,
            total_tokens=total,
            latency_seconds=reply.latency_seconds,
            finish_reason=reply.finish_reason,
            extra_usage={"offline": True},
            applied_settings={"mock": True},
            ignored_settings={},
        )


@dataclass
class _HttpBackend:
    provider_name: str
    model_endpoint: str
    transport: Transport
    api_key: str
    timeout_s: float = 60.0

    def _post(self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
        response = self.transport.send(
            HttpRequest(
                method="POST",
                url=url,
                headers=headers,
                body=dump_json(payload),
                timeout_s=self.timeout_s,
            )
        )
        if response.status >= 400:
            raise status_error(response)
        return read_json_object(response.body), response.latency_seconds


class OpenAIBackend(_HttpBackend):
    provider_name = "openai"

    def __init__(
        self,
        *,
        transport: Transport,
        api_key: str,
        timeout_s: float = 60.0,
        endpoint: str = OPENAI_URL,
    ) -> None:
        super().__init__("openai", endpoint, transport, api_key, timeout_s)

    def complete(
        self,
        *,
        model_id: str,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> Completion:
        payload, applied, ignored = _openai_payload(
            model_id,
            system_text,
            user_text,
            settings,
            token_field=str(settings.get("openai_token_field", "max_completion_tokens")),
        )
        data, latency = self._post(
            self.model_endpoint,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        return _from_chat_completion(data, latency, applied, ignored, reasoning_in_completion=True)


class GrokBackend(_HttpBackend):
    provider_name = "xai"

    def __init__(
        self,
        *,
        transport: Transport,
        api_key: str,
        timeout_s: float = 60.0,
        endpoint: str = XAI_URL,
    ) -> None:
        super().__init__("xai", endpoint, transport, api_key, timeout_s)

    def complete(
        self,
        *,
        model_id: str,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> Completion:
        payload, applied, ignored = _grok_payload(model_id, system_text, user_text, settings)
        data, latency = self._post(
            self.model_endpoint,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        return _from_chat_completion(data, latency, applied, ignored, reasoning_in_completion=True)


class AnthropicBackend(_HttpBackend):
    provider_name = "anthropic"

    def __init__(
        self,
        *,
        transport: Transport,
        api_key: str,
        timeout_s: float = 60.0,
        endpoint: str = ANTHROPIC_URL,
    ) -> None:
        super().__init__("anthropic", endpoint, transport, api_key, timeout_s)

    def complete(
        self,
        *,
        model_id: str,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> Completion:
        payload, applied, ignored = _anthropic_payload(model_id, system_text, user_text, settings)
        version = str(settings.get("anthropic_version", ANTHROPIC_VERSION))
        applied["anthropic_version"] = version
        data, latency = self._post(
            self.model_endpoint,
            {
                "x-api-key": self.api_key,
                "anthropic-version": version,
                "Content-Type": "application/json",
            },
            payload,
        )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        text_parts: list[str] = []
        thinking_present = False
        content = data.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
                elif block.get("type") == "thinking":
                    thinking_present = True
        extra: dict[str, Any] = {}
        for cache_field in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            if cache_field in usage:
                extra[cache_field] = _int(usage.get(cache_field))
        if extra:
            extra["unpriced_details"] = sorted(extra)
        if thinking_present and "thinking_tokens" not in usage:
            extra["reasoning_tokens_reported"] = False
        reasoning = _int(usage.get("thinking_tokens"))
        return Completion(
            text="".join(text_parts),
            response_model_id=_str_or_none(data.get("model")),
            request_id=_str_or_none(data.get("id")),
            prompt_tokens=_int(usage.get("input_tokens")),
            completion_tokens=_int(usage.get("output_tokens")),
            reasoning_tokens=reasoning,
            total_tokens=_int(usage.get("input_tokens")) + _int(usage.get("output_tokens")),
            latency_seconds=latency,
            finish_reason=_str_or_none(data.get("stop_reason")),
            extra_usage=extra,
            applied_settings=applied,
            ignored_settings=ignored,
        )


class GeminiBackend(_HttpBackend):
    provider_name = "google"

    def __init__(
        self,
        *,
        transport: Transport,
        api_key: str,
        timeout_s: float = 60.0,
        root: str = GEMINI_ROOT,
    ) -> None:
        super().__init__("google", root.rstrip("/"), transport, api_key, timeout_s)

    def complete(
        self,
        *,
        model_id: str,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> Completion:
        payload, applied, ignored = _gemini_payload(system_text, user_text, settings)
        url = f"{self.model_endpoint}/models/{quote(model_id, safe='')}:generateContent"
        if "key=" in url or self.api_key in url:
            raise TransportError("refusing to place the API key in the Gemini URL", retryable=False)
        data, latency = self._post(
            url,
            {"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            payload,
        )
        parts: list[str] = []
        finish = None
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0] if isinstance(candidates[0], dict) else {}
            finish = _str_or_none(first.get("finishReason"))
            content = first.get("content") if isinstance(first.get("content"), dict) else {}
            raw_parts = content.get("parts")
            if isinstance(raw_parts, list):
                for part in raw_parts:
                    if not isinstance(part, dict) or part.get("thought") is True:
                        continue
                    if isinstance(part.get("text"), str):
                        parts.append(part["text"])
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        prompt = _int(usage.get("promptTokenCount"))
        completion = _int(usage.get("candidatesTokenCount"))
        reasoning = _int(usage.get("thoughtsTokenCount"))
        total = _int(usage.get("totalTokenCount")) or prompt + completion + reasoning
        return Completion(
            text="".join(parts),
            response_model_id=_str_or_none(data.get("modelVersion")),
            request_id=_str_or_none(data.get("responseId")),
            prompt_tokens=prompt,
            completion_tokens=completion,
            reasoning_tokens=reasoning,
            total_tokens=total,
            latency_seconds=latency,
            finish_reason=finish,
            extra_usage={"reasoning_billed_separately": True},
            applied_settings=applied,
            ignored_settings=ignored,
        )


def resolve_api_key(provider: str, api_key: str | None) -> str:
    if api_key:
        return api_key
    for name in _KEY_ENV.get(provider, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    expected = " or ".join(_KEY_ENV.get(provider, ("an API key",)))
    raise LookupError(expected)


def _openai_payload(
    model_id: str,
    system_text: str,
    user_text: str,
    settings: Mapping[str, Any],
    *,
    token_field: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    applied: dict[str, Any] = {}
    ignored: dict[str, str] = {}
    max_out = _max_output(settings)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        token_field: max_out,
    }
    applied[token_field] = max_out
    reasoning = settings.get("reasoning_effort")
    if reasoning is not None:
        payload["reasoning_effort"] = reasoning
        applied["reasoning_effort"] = reasoning
        if "temperature" in settings:
            ignored["temperature"] = (
                "omitted because reasoning_effort is set; OpenAI reasoning models reject sampling parameters"
            )
        if "top_p" in settings:
            ignored["top_p"] = "omitted because reasoning_effort is set"
    else:
        _copy_number(payload, applied, settings, "temperature")
        _copy_number(payload, applied, settings, "top_p")
    if "top_k" in settings:
        ignored["top_k"] = "OpenAI chat completions do not accept top_k"
    if settings.get("seed") is not None:
        payload["seed"] = settings["seed"]
        applied["seed"] = settings["seed"]
    if settings.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
        applied["response_format"] = "json_object"
    return payload, applied, ignored


def _grok_payload(
    model_id: str,
    system_text: str,
    user_text: str,
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    applied: dict[str, Any] = {}
    ignored: dict[str, str] = {}
    token_field = str(settings.get("grok_token_field", "max_tokens"))
    max_out = _max_output(settings)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        token_field: max_out,
    }
    applied[token_field] = max_out
    applied["output_cap_field"] = token_field
    if "reasoning_effort" in settings:
        ignored["reasoning_effort"] = (
            "OpenAI reasoning_effort is not sent to xAI; set grok_reasoning_effort"
        )
    grok_effort = settings.get("grok_reasoning_effort")
    if grok_effort is not None:
        payload["reasoning_effort"] = grok_effort
        applied["grok_reasoning_effort"] = grok_effort
        if "temperature" in settings:
            ignored["temperature"] = (
                "omitted because xAI does not document combining grok_reasoning_effort with temperature"
            )
        if "top_p" in settings:
            ignored["top_p"] = (
                "omitted because xAI does not document combining grok_reasoning_effort with top_p"
            )
    else:
        _copy_number(payload, applied, settings, "temperature")
        _copy_number(payload, applied, settings, "top_p")
    if "top_k" in settings:
        ignored["top_k"] = "xAI chat completions are not sent top_k"
    if settings.get("seed") is not None:
        ignored["seed"] = "xAI is not sent a seed; seed support is not assumed"
    if settings.get("json_mode", True):
        payload["response_format"] = {"type": "json_object"}
        applied["response_format"] = "json_object_requested_not_guaranteed"
    return payload, applied, ignored


def _anthropic_payload(
    model_id: str,
    system_text: str,
    user_text: str,
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    applied: dict[str, Any] = {}
    ignored: dict[str, str] = {}
    max_out = _max_output(settings)
    payload: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_out,
        "system": system_text,
        "messages": [{"role": "user", "content": user_text}],
    }
    applied["max_tokens"] = max_out
    thinking = settings.get("anthropic_thinking_budget_tokens")
    if thinking is not None:
        payload["thinking"] = {"type": "enabled", "budget_tokens": int(thinking)}
        applied["anthropic_thinking_budget_tokens"] = int(thinking)
        if "temperature" in settings:
            ignored["temperature"] = (
                "omitted while thinking is enabled; Anthropic does not share OpenAI's sampling rules"
            )
    else:
        _copy_number(payload, applied, settings, "temperature")
    _copy_number(payload, applied, settings, "top_p")
    if "top_k" in settings:
        payload["top_k"] = settings["top_k"]
        applied["top_k"] = settings["top_k"]
    if settings.get("seed") is not None:
        ignored["seed"] = "Anthropic messages are not sent a seed"
    if "reasoning_effort" in settings:
        ignored["reasoning_effort"] = (
            "not an Anthropic parameter; set anthropic_thinking_budget_tokens for models that support thinking"
        )
    if settings.get("json_mode", True):
        ignored["json_mode"] = "Anthropic has no json_object field; the shared prompt requests JSON"
    return payload, applied, ignored


def _gemini_payload(
    system_text: str,
    user_text: str,
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    applied: dict[str, Any] = {}
    ignored: dict[str, str] = {}
    generation: dict[str, Any] = {"maxOutputTokens": _max_output(settings)}
    applied["maxOutputTokens"] = generation["maxOutputTokens"]
    if "temperature" in settings:
        generation["temperature"] = settings["temperature"]
        applied["temperature"] = settings["temperature"]
    if "top_p" in settings:
        generation["topP"] = settings["top_p"]
        applied["topP"] = settings["top_p"]
    if "top_k" in settings:
        generation["topK"] = settings["top_k"]
        applied["topK"] = settings["top_k"]
    if settings.get("gemini_send_seed") and settings.get("seed") is not None:
        generation["seed"] = settings["seed"]
        applied["seed"] = "requested_not_guaranteed"
    elif settings.get("seed") is not None:
        ignored["seed"] = "Gemini seed is not sent unless gemini_send_seed is true"
    if settings.get("json_mode", True):
        generation["responseMimeType"] = "application/json"
        applied["responseMimeType"] = "application/json"
    budget = settings.get("gemini_thinking_budget")
    if budget is not None:
        generation["thinkingConfig"] = {"thinkingBudget": int(budget)}
        applied["gemini_thinking_budget"] = int(budget)
    if "reasoning_effort" in settings:
        ignored["reasoning_effort"] = "Gemini uses gemini_thinking_budget, not reasoning_effort"
    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": generation,
    }
    return payload, applied, ignored


def _from_chat_completion(
    data: Mapping[str, Any],
    latency: float,
    applied: dict[str, Any],
    ignored: dict[str, str],
    *,
    reasoning_in_completion: bool,
) -> Completion:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning = 0
    if isinstance(details, dict):
        reasoning = _int(details.get("reasoning_tokens"))
    text = ""
    finish = None
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish = _str_or_none(choices[0].get("finish_reason"))
        message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            chunks = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
                elif isinstance(part, str):
                    chunks.append(part)
            text = "".join(chunks)
    prompt = _int(usage.get("prompt_tokens"))
    completion = _int(usage.get("completion_tokens"))
    total = _int(usage.get("total_tokens")) or prompt + completion
    extra = {"reasoning_included_in_completion_tokens": reasoning_in_completion}
    return Completion(
        text=text,
        response_model_id=_str_or_none(data.get("model")),
        request_id=_str_or_none(data.get("id")),
        prompt_tokens=prompt,
        completion_tokens=completion,
        reasoning_tokens=reasoning,
        total_tokens=total,
        latency_seconds=latency,
        finish_reason=finish,
        extra_usage=extra,
        applied_settings=applied,
        ignored_settings=ignored,
    )


def _copy_number(
    payload: dict[str, Any],
    applied: dict[str, Any],
    settings: Mapping[str, Any],
    key: str,
) -> None:
    if key in settings:
        payload[key] = settings[key]
        applied[key] = settings[key]


def _max_output(settings: Mapping[str, Any]) -> int:
    value = settings.get("max_output_tokens", 800)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 800
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


DEFAULT_TRANSPORT = UrllibTransport
