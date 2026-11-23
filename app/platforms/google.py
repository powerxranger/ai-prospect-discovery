from __future__ import annotations

from urllib.parse import urlparse

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import GENERIC_PATHS, PlatformAdapter, host_matches_any, path_of

EXCLUDED_DOMAINS = {
    "google.com",
    "tavily.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "threads.net",
    "threads.com",
    "wa.me",
    "whatsapp.com",
}
PROFILE_WORDS = ("profile", "about", "contact", "team", "founder", "owner", "business")


class GoogleAdapter(PlatformAdapter):
    name = "Google"
    search_hint = "publicly indexed profiles and websites"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        return [f'"{focus}" "{location}" public profile contact'.replace('"" ', "").strip()]

    def accepts(self, result: SearchResult) -> bool:
        if host_matches_any(result.url, EXCLUDED_DOMAINS):
            return False
        parsed = urlparse(result.url)
        path = path_of(result.url)
        if path.lower() in GENERIC_PATHS:
            return False
        if parsed.query and not any(word in path.lower() for word in PROFILE_WORDS):
            return False
        return len([part for part in path.split("/") if part]) >= 1
