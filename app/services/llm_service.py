from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Settings
from ..errors import LLMConfigurationError, LLMResponseError
from ..utils.prompts import CORRECTION_SUFFIX
from ..utils.validators import sanitize_text

logger = logging.getLogger(__name__)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model response, allowing code fences."""
    if not text:
        return None
    cleaned = sanitize_text(text, 50_000)
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class LLMService:
    """Small provider-agnostic JSON-only LLM client."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self._key = settings.active_llm_key()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "prospect-discovery/1.0"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate_json(self, system: str, user_prompt: str) -> dict[str, Any]:
        if self.provider == "none" or self._key is None:
            raise LLMConfigurationError()
        key_value = self._key.get_secret_value()
        prompt = user_prompt
        for attempt in range(self.settings.llm_max_retries + 1):
            if attempt:
                prompt = user_prompt + CORRECTION_SUFFIX
            try:
                raw = await self._request(system, prompt, key_value)
            except LLMResponseError:
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                logger.warning("LLM request failed with HTTP %s", status)
                if status == 429:
                    raise LLMResponseError("The language model is rate limited.") from None
                raise LLMResponseError() from None
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                logger.warning("LLM request failed")
                raise LLMResponseError() from None
            parsed = extract_json_object(raw)
            if parsed is not None:
                return parsed
            logger.warning("LLM returned non-JSON output (attempt %s)", attempt + 1)
        raise LLMResponseError()

    async def _request(self, system: str, prompt: str, key_value: str) -> str:
        if self.provider == "gemini":
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent"
            )
            payload: dict[str, Any] = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                    "maxOutputTokens": 1600,
                },
            }
            response = await self._client.post(
                url,
                json=payload,
                headers={"x-goog-api-key": key_value},
            )
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(str(part.get("text", "")) for part in parts)

        if self.provider in {"groq", "openai"}:
            base = (
                "https://api.groq.com/openai/v1"
                if self.provider == "groq"
                else "https://api.openai.com/v1"
            )
            payload = {
                "model": self.model,
                "temperature": 0.1,
                "max_tokens": 1600,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
            response = await self._client.post(
                f"{base}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {key_value}"},
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])

        raise LLMConfigurationError()
