from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import parse_qs, urlparse

from ..schemas import Candidate, PlatformName, QueryIntent
from ..services.search_service import SearchResult
from ..utils.normalizers import (
    extract_name,
    extract_platform_handle,
    location_label,
)
from ..utils.validators import sanitize_text

GENERIC_PATHS = {
    "",
    "/",
    "/search",
    "/results",
    "/home",
    "/login",
    "/signup",
    "/explore",
    "/discover",
    "/about",
    "/privacy",
    "/terms",
}


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def path_of(url: str) -> str:
    try:
        return urlparse(url).path.rstrip("/") or "/"
    except ValueError:
        return "/"


def host_matches_any(url: str, domains: set[str]) -> bool:
    host = host_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def has_query(url: str, *keys: str) -> bool:
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return False
    return any(key in query for key in keys)


class PlatformAdapter(ABC):
    name: PlatformName
    search_hint: str = ""

    def query_parts(self, intent: QueryIntent) -> tuple[str, str]:
        focus = sanitize_text(intent.audience or intent.interest, 120)
        location = " ".join(value for value in (intent.city, intent.state, intent.country) if value)
        return focus, location

    @abstractmethod
    def build_queries(self, intent: QueryIntent) -> list[str]:
        """Return authorized public search queries for this platform."""

    @abstractmethod
    def accepts(self, result: SearchResult) -> bool:
        """Return True when a result looks like this platform's public profile."""

    def extract(self, result: SearchResult, intent: QueryIntent) -> Candidate | None:
        name = extract_name(result.title, result.snippet, result.url)
        handle = extract_platform_handle(result.url, self.name)
        if not name:
            return None
        handles = [handle] if handle else []
        return Candidate(
            name=name,
            platform=self.name,
            url=result.url,
            title=sanitize_text(result.title, 300),
            snippet=sanitize_text(result.snippet, 800),
            evidence=sanitize_text(f"{result.title}. {result.snippet}".strip(". "), 1_000),
            location=location_label(intent.city, intent.state, intent.country),
            handles=handles,
            source_query=result.source_query,
        )
