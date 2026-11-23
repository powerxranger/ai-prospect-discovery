from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.errors import SearchUnavailableError
from app.services.search_service import SearchService


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_tavily_search_parses_public_results(
    settings, cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["api_key"] == "dummy-tavily-key-1234"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "John Smith | Football Coach",
                        "url": "https://www.linkedin.com/in/john-smith-football/",
                        "content": "Football coach in Washington DC.",
                        "score": 0.9,
                    },
                    {
                        "title": "Internal",
                        "url": "http://127.0.0.1/admin",
                        "content": "Private",
                    },
                ]
            },
        )

    service = SearchService(settings, cache, _client(handler))
    results = await service.search("football Washington DC")
    assert len(results) == 1
    assert "linkedin.com" in results[0].url
    await service.aclose()


async def test_tavily_retries_rate_limit(settings, cache, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"results": []})

    service = SearchService(settings, cache, _client(handler))
    assert await service.search("query") == []
    assert calls == 2
    await service.aclose()


async def test_search_many_tolerates_partial_failure(settings, cache) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    service = SearchService(settings, cache, _client(handler))

    async def fake_search(query: str):
        if query == "bad":
            raise SearchUnavailableError()
        return []

    service.search = fake_search  # type: ignore[method-assign]
    assert await service.search_many(["good", "bad"]) == []
    with pytest.raises(SearchUnavailableError):
        await service.search_many(["bad"])


async def test_search_result_cache_is_used(settings, cache) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": []})

    service = SearchService(settings, cache, _client(handler))
    await service.search("cached query")
    await service.search("cached query")
    assert calls == 1
    await service.aclose()
