from __future__ import annotations

from urllib.parse import urlparse

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, has_query, host_matches_any, path_of

DOMAINS = {"wa.me", "api.whatsapp.com"}


class WhatsAppAdapter(PlatformAdapter):
    name = "WhatsApp"
    search_hint = "publicly published contact links"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'"{focus}" "{location}" "wa.me"'.replace('"" ', "").strip()
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        if host_of_is_wame(result.url):
            parts = [part for part in path_of(result.url).split("/") if part]
            return len(parts) == 1 and parts[0].isdigit()
        return has_query(result.url, "phone")


def host_of_is_wame(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".") == "wa.me"
    except ValueError:
        return False
