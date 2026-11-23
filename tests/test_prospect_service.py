from __future__ import annotations

from app.services.prospect_service import ProspectService
from app.services.search_service import SearchResult
from tests.conftest import FakeFetcher, FakeLLM, FakeSearch


def _result(url: str, title: str, platform_query: str) -> SearchResult:
    return SearchResult(
        title=title,
        url=url,
        snippet="John Smith is a football coach in Washington DC.",
        source_query=platform_query,
        score=0.9,
    )


async def test_orchestrator_discovers_validates_deduplicates_and_caches(settings, cache) -> None:
    llm = FakeLLM(
        [
            {
                "interest": "Football",
                "audience": "Football lovers",
                "city": "Washington DC",
                "state": "District of Columbia",
                "country": "USA",
                "target_type": "individual",
            },
            {
                "candidates": [
                    {
                        "index": 0,
                        "name": "John Smith",
                        "location": "Washington DC",
                        "relevance_score": 0.9,
                        "evidence": "football coach in Washington DC",
                    },
                    {
                        "index": 1,
                        "name": "John Smith",
                        "location": "Washington DC",
                        "relevance_score": 0.9,
                        "evidence": "football coach in Washington DC",
                    },
                ]
            },
        ]
    )
    search = FakeSearch(
        [
            _result(
                "https://www.linkedin.com/in/johnsmithfootball/",
                "John Smith | Football Coach | Washington DC",
                "linkedin",
            ),
            _result(
                "https://www.instagram.com/johnsmithfootball/",
                "John Smith (@johnsmithfootball) Football Washington DC",
                "instagram",
            ),
        ]
    )
    service = ProspectService(settings, cache, llm, search, FakeFetcher({}))
    query = "Football lovers in Washington DC in USA"

    first = await service.discover(query)
    assert first.total_prospects == 1
    assert first.prospects[0].name == "John Smith"
    assert {item.platform for item in first.prospects[0].social_link} == {"LinkedIn", "Instagram"}
    assert len(search.queries) == 9

    second = await service.discover(query)
    assert second == first
    assert len(search.queries) == 9
    await service.aclose()
