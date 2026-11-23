from __future__ import annotations

import json

import httpx
import pytest

from app.errors import LLMConfigurationError, LLMResponseError
from app.services.llm_service import LLMService, extract_json_object


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gemini_json_request(settings) -> None:
    settings.llm_provider = "gemini"
    payload = {"interest": "Football", "audience": "Football lovers"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "generativelanguage.googleapis.com" in str(request.url)
        assert request.headers.get("x-goog-api-key") == "dummy-gemini-key-1234"
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        )

    service = LLMService(settings, _client(handler))
    assert await service.generate_json("system", "user") == payload
    await service.aclose()


async def test_groq_json_request(settings) -> None:
    settings.llm_provider = "groq"
    settings.llm_model = "qwen/qwen3.8-27b"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://api.groq.com/openai/v1/chat/completions")
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    service = LLMService(settings, _client(handler))
    assert await service.generate_json("system", "user") == {"ok": True}
    await service.aclose()


async def test_invalid_json_is_retried_once(settings) -> None:
    settings.llm_provider = "gemini"
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        text = "not json" if len(calls) == 1 else '{"ok": true}'
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
        )

    service = LLMService(settings, _client(handler))
    assert await service.generate_json("system", "user") == {"ok": True}
    assert len(calls) == 2
    await service.aclose()


async def test_rate_limit_raises_clean_error(settings) -> None:
    settings.llm_provider = "gemini"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    service = LLMService(settings, _client(handler))
    with pytest.raises(LLMResponseError):
        await service.generate_json("system", "user")
    await service.aclose()


async def test_missing_key_raises_configuration_error(settings) -> None:
    settings.llm_provider = "none"
    service = LLMService(settings, _client(lambda request: httpx.Response(200)))
    with pytest.raises(LLMConfigurationError):
        await service.generate_json("system", "user")
    await service.aclose()


def test_extract_json_object_handles_fences() -> None:
    text = 'Here you go:\n```json\n{"a": 1}\n```'
    assert extract_json_object(text) == {"a": 1}
    assert extract_json_object("no json here") is None
