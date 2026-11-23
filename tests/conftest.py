from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.schemas import Candidate
from app.services.cache import TTLCache
from app.services.llm_service import LLMService
from app.services.safe_http import SafeFetchResult, SafeHTTPClient
from app.services.search_service import SearchResult, SearchService


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="none",
        llm_model="test-model",
        gemini_api_key=SecretStr("dummy-gemini-key-1234"),
        groq_api_key=SecretStr("dummy-groq-key-1234"),
        openai_api_key=SecretStr("dummy-openai-key-1234"),
        tavily_api_key=SecretStr("dummy-tavily-key-1234"),
        request_timeout_seconds=5.0,
        search_concurrency=2,
        max_search_results_per_query=5,
        max_candidates=24,
        max_profile_fetches=10,
        safe_fetch_max_bytes=10_000,
        safe_fetch_max_chars=5_000,
        cache_ttl_seconds=60,
        llm_max_retries=1,
    )


@pytest.fixture
def cache(settings: Settings) -> TTLCache:
    return TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)


class FakeLLM(LLMService):
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    async def generate_json(self, system: str, user_prompt: str) -> dict:
        self.calls.append((system, user_prompt))
        if not self.responses:
            raise RuntimeError("no fake response")
        return self.responses.pop(0)

    async def aclose(self) -> None:
        return None


class FakeSearch(SearchService):
    def __init__(
        self, results: list[SearchResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = list(results or [])
        self.error = error
        self.queries: list[str] = []

    async def search_many(self, queries: list[str]) -> list[SearchResult]:
        self.queries.extend(queries)
        if self.error:
            raise self.error
        return self.results

    async def aclose(self) -> None:
        return None


class FakeFetcher(SafeHTTPClient):
    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages or {}
        self.calls: list[str] = []

    async def get_text(self, url: str) -> SafeFetchResult | None:
        self.calls.append(url)
        if url not in self.pages:
            return None
        return SafeFetchResult(url=url, text=self.pages[url], content_type="text/html")

    async def aclose(self) -> None:
        return None


def make_candidate(
    name: str = "John Smith",
    platform: str = "LinkedIn",  # type: ignore[assignment]
    url: str = "https://www.linkedin.com/in/john-smith-football/",
    handles: list[str] | None = None,
    score: float = 0.8,
) -> Candidate:
    return Candidate(
        name=name,
        platform=platform,
        url=url,
        title=f"{name} | Football Coach | Washington DC",
        snippet=f"{name} is a football coach in Washington DC.",
        evidence=f"{name} is a football coach in Washington DC.",
        location="Washington DC, District of Columbia, USA",
        handles=handles or ["john-smith-football"],
        relevance_score=score,
    )
