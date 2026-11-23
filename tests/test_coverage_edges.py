from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import get_settings
from app.logging_config import configure_logging
from app.platforms.base import has_query, host_matches_any, host_of, path_of
from app.platforms.facebook import FacebookAdapter
from app.platforms.google import GoogleAdapter
from app.platforms.instagram import InstagramAdapter
from app.platforms.linkedin import LinkedInAdapter
from app.platforms.threads import ThreadsAdapter
from app.platforms.whatsapp import WhatsAppAdapter, host_of_is_wame
from app.platforms.x_platform import XAdapter
from app.platforms.youtube import YouTubeAdapter
from app.schemas import DiscoveryRequest, QueryIntent, SocialLink
from app.services.cache import TTLCache
from app.services.contact_service import _phone_from_link
from app.services.deduplication_service import DeduplicationService, UnionFind, should_merge
from app.services.llm_service import LLMService, extract_json_object
from app.services.profile_extractor import ProfileExtractor
from app.services.relevance_service import (
    LLMValidationCandidate,
    RelevanceService,
    _mentions,
    _terms,
    candidate_index,
    deterministic_score,
)
from app.services.safe_http import SafeHTTPClient
from app.services.search_service import SearchResult, SearchService
from app.utils.normalizers import (
    evidence_text,
    extract_platform_handle,
    location_label,
    plausible_name,
)
from app.utils.validators import (
    extract_emails,
    extract_phone_numbers,
    host_matches,
    is_public_http_url,
    normalize_phone_number,
    validate_email_address,
)
from tests.conftest import FakeLLM, make_candidate


def _public_dns(*args: Any, **kwargs: Any) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _raise_value_error(*args: Any, **kwargs: Any) -> Any:
    raise ValueError("bad value")


def _intent_no_location() -> QueryIntent:
    return QueryIntent(interest="Football", audience="Football lovers")


def _intent_with_location() -> QueryIntent:
    return QueryIntent(
        interest="Football",
        audience="Football lovers",
        city="Washington DC",
        state="District of Columbia",
        country="USA",
    )


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://metadata/", "internal hostname"),
        ("https://" + "a" * 64 + ".com/", "invalid hostname"),
        ("https://exa_mple.com/", "invalid hostname"),
        ("https://example/", "hostname must include a TLD"),
    ],
)
def test_url_shape_rejections(url: str, reason: str) -> None:
    safe, actual = is_public_http_url(url, resolve_dns=False)
    assert safe is False
    assert actual == reason


def test_url_parser_exception_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.urlparse", _raise_value_error)
    assert is_public_http_url("https://example.com") == (False, "malformed URL")


def test_missing_hostname_is_rejected() -> None:
    assert is_public_http_url("https:///path", resolve_dns=False) == (False, "hostname is required")


@pytest.mark.parametrize(
    ("dns", "reason"),
    [
        (lambda *args, **kwargs: [], "DNS resolution failed"),
        (lambda *args, **kwargs: [(2, 1, 6, "", ("not-an-ip", 443))], "invalid resolved address"),
    ],
)
def test_dns_edge_cases_are_rejected(
    dns: Any, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", dns)
    safe, actual = is_public_http_url("https://example.com/")
    assert safe is False
    assert actual == reason


def test_dns_gaierror_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def gaierror(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror("not found")

    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", gaierror)
    assert is_public_http_url("https://example.com/")[0] is False


def test_email_phone_and_host_helpers_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert validate_email_address("a" * 250 + "@example.com") is None
    assert normalize_phone_number("+" + "9" * 20) is None
    assert normalize_phone_number("+1 000 000 0000", "US") is None
    assert extract_emails("john@example.com john@example.com") == ["john@example.com"]
    assert extract_phone_numbers("+1 202 555 0123 or +1 202 555 0123") == ["+12025550123"]
    assert host_matches("https://www.linkedin.com/in/john/", {"linkedin.com"}) is True
    monkeypatch.setattr("app.utils.validators.urlparse", _raise_value_error)
    assert host_matches("bad", {"linkedin.com"}) is False


def test_normalizer_edge_cases() -> None:
    assert plausible_name("") is False
    assert plausible_name(" ".join(["John"] * 7)) is False
    assert plausible_name("LinkedIn Profile") is False
    assert plausible_name("http://example.com") is False
    assert extract_platform_handle("https://facebook.com/profile.php?id=12345", "Facebook") == (
        "12345"
    )
    assert extract_platform_handle("https://youtube.com/channel/UCabc123", "YouTube") == "ucabc123"
    assert extract_platform_handle("https://google.com/maps/place/john-smith", "Google") == (
        "john-smith"
    )
    assert extract_platform_handle("https://wa.me/?phone=12025550123", "WhatsApp") == (
        "12025550123"
    )
    assert location_label(None, None, None) == "Location not published"
    assert location_label("London", "London", "UK") == "London, UK"
    assert evidence_text(None, "hello ", "world") == "hello world"


def test_extract_json_object_edge_cases() -> None:
    assert extract_json_object("") is None
    assert extract_json_object("```not json```") is None
    assert extract_json_object('{"broken":') is None
    assert extract_json_object("[1, 2]") is None


async def test_llm_http_error_branches(settings) -> None:
    settings.llm_provider = "gemini"

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    service = LLMService(settings, _client(server_error))
    with pytest.raises(Exception):  # noqa: B017
        await service.generate_json("system", "user")
    await service.aclose()

    def connection_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    service = LLMService(settings, _client(connection_error))
    with pytest.raises(Exception):  # noqa: B017
        await service.generate_json("system", "user")
    await service.aclose()


async def test_llm_retry_exhaustion(settings) -> None:
    settings.llm_provider = "gemini"
    settings.llm_max_retries = 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
        )

    service = LLMService(settings, _client(handler))
    with pytest.raises(Exception):  # noqa: B017
        await service.generate_json("system", "user")
    await service.aclose()


async def test_openai_provider_branch(settings) -> None:
    settings.llm_provider = "openai"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    service = LLMService(settings, _client(handler))
    assert await service.generate_json("system", "user") == {"ok": True}
    await service.aclose()


async def test_owned_http_clients_are_closed(settings) -> None:
    await LLMService(settings).aclose()
    await SearchService(settings, TTLCache(60, 2)).aclose()
    await SafeHTTPClient(settings).aclose()


async def test_cache_disabled_expiry_and_eviction() -> None:
    disabled = TTLCache(0, 2)
    await disabled.set("key", "value")
    assert await disabled.get("key") is None

    expiring = TTLCache(1, 2)
    await expiring.set("key", "value")
    expiring._data["key"] = (0.0, "value")
    assert await expiring.get("key") is None
    assert "key" not in expiring._data

    bounded = TTLCache(60, 1)
    await bounded.set("a", 1)
    await bounded.set("b", 2)
    assert await bounded.get("a") is None
    assert await bounded.get("b") == 2


async def test_safe_http_error_branches(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)

    def no_location(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    assert (
        await SafeHTTPClient(settings, _client(no_location)).get_text(
            "https://public.example.com/start"
        )
        is None
    )

    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert (
        await SafeHTTPClient(settings, _client(not_found)).get_text(
            "https://public.example.com/missing"
        )
        is None
    )

    def connection_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    assert (
        await SafeHTTPClient(settings, _client(connection_error)).get_text(
            "https://public.example.com/error"
        )
        is None
    )

    settings.max_redirects = 0

    def redirect_forever(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://public.example.com/next"})

    assert (
        await SafeHTTPClient(settings, _client(redirect_forever)).get_text(
            "https://public.example.com/start"
        )
        is None
    )


async def test_search_service_error_branches(
    settings, cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.tavily_api_key = None
    service = SearchService(settings, cache)
    with pytest.raises(Exception):  # noqa: B017
        await service.search("query")
    await service.aclose()

    async def no_sleep(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    service = SearchService(settings, cache, _client(server_error))
    settings.tavily_api_key = SecretStr("dummy-tavily-key-1234")
    service._key = settings.tavily_api_key
    with pytest.raises(Exception):  # noqa: B017
        await service.search("query")
    await service.aclose()

    def connection_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    service = SearchService(settings, cache, _client(connection_error))
    with pytest.raises(Exception):  # noqa: B017
        await service.search("different query")
    await service.aclose()

    calls = 0

    def rate_limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    service = SearchService(settings, cache, _client(rate_limited))
    with pytest.raises(Exception):  # noqa: B017
        await service.search("rate limited query")
    assert calls == 3
    await service.aclose()


async def test_search_many_empty_and_duplicate_merge(settings, cache) -> None:
    service = SearchService(settings, cache, _client(lambda request: httpx.Response(200)))
    assert await service.search_many([]) == []

    async def duplicate_results(query: str) -> list[SearchResult]:
        return [
            SearchResult(url="https://example.com/profile/"),
            SearchResult(url="https://example.com/profile?x=1"),
        ]

    service.search = duplicate_results  # type: ignore[method-assign]
    assert len(await service.search_many(["query"])) == 1


def test_profile_extractor_exception_branches(settings) -> None:
    extractor = ProfileExtractor(settings)
    adapter = extractor.adapters[0]

    def boom(intent: QueryIntent) -> list[str]:
        raise RuntimeError("boom")

    adapter.build_queries = boom
    try:
        queries = extractor.build_queries(_intent_with_location())
        assert "site:linkedin.com" not in queries
        assert any("x.com" in query for query in queries)
    finally:
        delattr(adapter, "build_queries")

    def reject(result: SearchResult) -> bool:
        raise RuntimeError("boom")

    adapter.accepts = reject
    try:
        result = SearchResult(
            title="John Smith",
            url="https://www.linkedin.com/in/john-smith/",
            snippet="Football in Washington DC",
        )
        assert extractor.build_candidates([result], _intent_with_location()) == []
    finally:
        delattr(adapter, "accepts")


def test_profile_extractor_respects_candidate_limit(settings) -> None:
    settings.max_candidates = 1
    extractor = ProfileExtractor(settings)
    results = [
        SearchResult(title="John Smith", url="https://www.linkedin.com/in/john-smith/"),
        SearchResult(title="Jane Doe", url="https://www.instagram.com/jane-doe/"),
    ]
    assert len(extractor.build_candidates(results, _intent_with_location())) == 1


def test_google_adapter_path_rules() -> None:
    adapter = GoogleAdapter()
    assert adapter.accepts(SearchResult(url="https://www.google.com/search?q=football")) is False
    assert adapter.accepts(SearchResult(url="https://example.com/")) is False
    assert adapter.accepts(SearchResult(url="https://example.com/blog?x=1")) is False
    assert adapter.accepts(SearchResult(url="https://example.com/profile/john?x=1")) is True
    assert adapter.accepts(SearchResult(url="https://example.com/john-smith")) is True


def test_platform_queries_without_location() -> None:
    intent = _intent_no_location()
    for adapter in (
        LinkedInAdapter(),
        XAdapter(),
        YouTubeAdapter(),
        InstagramAdapter(),
        FacebookAdapter(),
        ThreadsAdapter(),
        WhatsAppAdapter(),
    ):
        queries = adapter.build_queries(intent)
        assert len(queries) == 1
        assert "Football lovers" in queries[0]


def test_platform_acceptance_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert FacebookAdapter().accepts(SearchResult(url="https://facebook.com/profile.php?id=1"))
    assert WhatsAppAdapter().accepts(
        SearchResult(url="https://api.whatsapp.com/send?phone=12025550123")
    )
    assert YouTubeAdapter().accepts(SearchResult(url="https://youtu.be/")) is False
    monkeypatch.setattr("app.platforms.whatsapp.urlparse", _raise_value_error)
    assert host_of_is_wame("https://wa.me/12025550123") is False


def test_base_helpers_handle_malformed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.platforms.base.urlparse", _raise_value_error)
    assert host_of("bad") == ""
    assert path_of("bad") == "/"
    assert has_query("bad", "id") is False
    assert host_matches_any("bad", {"example.com"}) is False


async def test_relevance_edge_branches() -> None:
    service = RelevanceService(FakeLLM([]))
    assert await service.refine([], _intent_with_location()) == []
    assert len(await service.refine([make_candidate()], _intent_with_location())) == 1
    assert _terms(None) == set()
    assert _mentions(None, "anything") is False
    assert candidate_index([], make_candidate()) == -1

    candidate = make_candidate()
    candidate.location = ""
    service._apply_llm_data(
        candidate,
        LLMValidationCandidate(index=0, location="Miami"),
        "john smith football washington dc",
    )
    assert candidate.location == "Location not published"


async def test_relevance_skips_when_no_topic_terms() -> None:
    intent = QueryIntent.model_construct(
        interest="",
        audience="",
        city="Washington DC",
        state=None,
        country=None,
    )
    fake = FakeLLM([])
    assert await RelevanceService(fake).refine([make_candidate()], intent) == []


def test_relevance_score_edge_branches() -> None:
    candidate = make_candidate(
        name="Profile",
        platform="Google",  # type: ignore[arg-type]
        url="https://example.com/profile",
        handles=[],
    )
    score = deterministic_score(candidate, _intent_with_location())
    assert 0.0 <= score <= 1.0


def test_contact_phone_link_fallbacks() -> None:
    assert _phone_from_link("https://api.whatsapp.com/send?phone=12025550123", "US") == (
        "+12025550123"
    )
    assert _phone_from_link("https://web.whatsapp.com/send?phone=12025550123", "US") == (
        "+12025550123"
    )
    assert _phone_from_link("message me on wa.me/12025550123", "US") == "+12025550123"


def test_deduplication_identity_edges() -> None:
    candidate = make_candidate()
    assert should_merge(candidate, candidate) is True
    assert (
        should_merge(
            make_candidate(name="Profile", url="https://www.linkedin.com/in/profile/"),
            candidate,
        )
        is False
    )
    assert (
        should_merge(
            candidate,
            make_candidate(
                name="Jane Doe",
                url="https://www.linkedin.com/in/jane-doe-football/",
                handles=["jane-doe-football"],
            ),
        )
        is False
    )

    finder = UnionFind(1)
    finder.union(0, 0)
    assert finder.find(0) == 0

    default_location = make_candidate()
    default_location.location = ""
    response = DeduplicationService().consolidate([default_location], "query")
    assert response.prospects[0].location == "Location not published"


def test_schema_validation_edges() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(query=" \x00 ")
    with pytest.raises(ValidationError):
        QueryIntent(interest=" ", audience="Football")
    with pytest.raises(ValidationError):
        SocialLink(platform="Email", link="mailto:bad")
    with pytest.raises(ValidationError):
        SocialLink(platform="LinkedIn", link="ftp://example.com")
    with pytest.raises(ValidationError):
        SocialLink(platform="LinkedIn", link="https://user:pass@example.com")


def test_config_secret_branches(settings) -> None:
    settings.llm_provider = "openai"
    assert settings.active_llm_key() is settings.openai_api_key
    settings.llm_provider = "none"
    assert settings.active_llm_key() is None
    settings.gemini_api_key = SecretStr("short")
    settings.groq_api_key = None
    settings.openai_api_key = None
    settings.tavily_api_key = SecretStr("12345678")
    assert settings.configured_secrets() == ["12345678"]
    assert get_settings().app_name == "AI Prospect Discovery API"


def test_logging_creates_handler_once(settings) -> None:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        root.handlers.clear()
        configure_logging(settings)
        assert len(root.handlers) == 1
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = old_handlers
        root.setLevel(old_level)
