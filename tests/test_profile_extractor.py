from __future__ import annotations

import pytest

from app.config import Settings
from app.platforms.email import EmailAdapter
from app.schemas import QueryIntent
from app.services.profile_extractor import ProfileExtractor
from app.services.search_service import SearchResult


@pytest.fixture
def intent() -> QueryIntent:
    return QueryIntent(
        interest="Football",
        audience="Football lovers",
        city="Washington DC",
        state="District of Columbia",
        country="USA",
        target_type="individual",
    )


def _result(url: str, title: str = "John Smith") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="Football in Washington DC", source_query="q")


def test_all_platforms_generate_queries(settings: Settings, intent: QueryIntent) -> None:
    extractor = ProfileExtractor(settings)
    queries = extractor.build_queries(intent)
    assert len(queries) == 9
    assert any("site:linkedin.com" in query for query in queries)
    assert any("site:x.com" in query for query in queries)
    assert any("site:youtube.com" in query for query in queries)
    assert any("site:instagram.com" in query for query in queries)
    assert any("site:facebook.com" in query for query in queries)
    assert any("threads" in query for query in queries)
    assert any("wa.me" in query for query in queries)
    assert any("email contact" in query for query in queries)


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.linkedin.com/in/john-smith/", "LinkedIn"),
        ("https://x.com/johnsmith", "X"),
        ("https://www.youtube.com/@johnsmith", "YouTube"),
        ("https://www.instagram.com/johnsmith/", "Instagram"),
        ("https://www.facebook.com/johnsmith/", "Facebook"),
        ("https://www.threads.net/@johnsmith", "Threads"),
        ("https://wa.me/12025550123", "WhatsApp"),
        ("https://johnsmith.example.com/contact", "Email"),
    ],
)
def test_profile_urls_are_recognized(
    url: str, platform: str, settings: Settings, intent: QueryIntent
) -> None:
    extractor = ProfileExtractor(settings)
    candidate = extractor.build_candidates([_result(url)], intent)[0]
    assert candidate.platform == platform
    assert candidate.name == "John Smith"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com/search?q=football",
        "https://www.linkedin.com/search/results/people/",
        "https://x.com/search?q=football",
        "https://www.youtube.com/watch?v=abc",
        "https://www.instagram.com/p/ABC123/",
        "https://www.facebook.com/search/top/",
        "https://www.threads.net/login",
    ],
)
def test_generic_urls_are_rejected(url: str, settings: Settings, intent: QueryIntent) -> None:
    extractor = ProfileExtractor(settings)
    assert extractor.build_candidates([_result(url)], intent) == []


def test_extractor_deduplicates_same_url(settings: Settings, intent: QueryIntent) -> None:
    extractor = ProfileExtractor(settings)
    result = _result("https://www.linkedin.com/in/john-smith/")
    candidates = extractor.build_candidates([result, result], intent)
    assert len(candidates) == 1


def test_email_adapter_rejects_social_video_and_post_urls() -> None:
    adapter = EmailAdapter()
    assert (
        adapter.accepts(
            SearchResult(title="Contact email", url="https://www.youtube.com/watch?v=abc")
        )
        is False
    )
    assert (
        adapter.accepts(
            SearchResult(title="Contact email", url="https://www.instagram.com/p/ABC123/")
        )
        is False
    )
    assert (
        adapter.accepts(SearchResult(title="Contact", url="https://johnsmith.example.com/contact"))
        is True
    )


def test_extractor_skips_results_without_a_name(settings: Settings, intent: QueryIntent) -> None:
    extractor = ProfileExtractor(settings)
    result = _result("https://www.linkedin.com/in/john-smith/", title="Profile | LinkedIn")
    result.snippet = ""
    assert extractor.build_candidates([result], intent) == []
