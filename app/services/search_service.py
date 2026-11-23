from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from ..config import Settings
from ..errors import SearchUnavailableError
from ..utils.validators import is_public_http_url, normalize_url, sanitize_text
from .cache import TTLCache

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str
    snippet: str = ""
    score: float = 0.0
    source_query: str = ""


class SearchService:
    """Tavily-backed public web discovery with partial-failure tolerance."""

    endpoint = "https://api.tavily.com/search"

    def __init__(
        self,
        settings: Settings,
        cache: TTLCache,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self._key = settings.tavily_api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "prospect-discovery/1.0"},
        )
        self._semaphore = asyncio.Semaphore(settings.search_concurrency)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, query: str) -> list[SearchResult]:
        if self._key is None:
            raise SearchUnavailableError("Tavily API key is not configured.")
        clean_query = sanitize_text(query, 400)
        key = TTLCache.key({"tavily": clean_query})
        cached = await self.cache.get(key)
        if cached is not None:
            return [SearchResult.model_validate(item) for item in cached]

        payload = {
            "api_key": self._key.get_secret_value(),
            "query": clean_query,
            "search_depth": "basic",
            "max_results": self.settings.max_search_results_per_query,
            "include_answer": False,
            "include_raw_content": False,
        }
        data: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                async with self._semaphore:
                    response = await self._client.post(self.endpoint, json=payload)
                if response.status_code == 429:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                logger.warning("Tavily HTTP %s", exc.response.status_code)
                raise SearchUnavailableError() from None
            except (httpx.HTTPError, ValueError):
                logger.warning("Tavily request failed")
                raise SearchUnavailableError() from None
        if data is None:
            raise SearchUnavailableError("Tavily rate limit was reached.")

        results: list[SearchResult] = []
        for item in data.get("results", [])[: self.settings.max_search_results_per_query]:
            url = sanitize_text(str(item.get("url", "")), 2_000)
            safe, _ = is_public_http_url(url, resolve_dns=False)
            if not safe:
                continue
            results.append(
                SearchResult(
                    title=sanitize_text(str(item.get("title", "")), 300),
                    url=url,
                    snippet=sanitize_text(str(item.get("content", item.get("snippet", ""))), 800),
                    score=float(item.get("score", 0.0) or 0.0),
                    source_query=clean_query,
                )
            )
        await self.cache.set(key, [item.model_dump() for item in results])
        return results

    async def search_many(self, queries: list[str]) -> list[SearchResult]:
        if not queries:
            return []
        responses = await asyncio.gather(
            *(self.search(query) for query in queries),
            return_exceptions=True,
        )
        merged: dict[str, SearchResult] = {}
        successes = 0
        for response in responses:
            if isinstance(response, BaseException):
                logger.info("One discovery query failed: %s", type(response).__name__)
                continue
            successes += 1
            for result in response:
                merged.setdefault(normalize_url(result.url), result)
        if successes == 0:
            raise SearchUnavailableError()
        return list(merged.values())[: self.settings.max_candidates * 2]
