from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, host_matches_any, path_of

DOMAINS = {"instagram.com"}
RESERVED = {"p", "reel", "reels", "tv", "explore", "accounts", "about", "legal", "privacy"}


class InstagramAdapter(PlatformAdapter):
    name = "Instagram"
    search_hint = "public profiles"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'site:instagram.com "{focus}"' if focus else "site:instagram.com"
        if location:
            query += f' "{location}"'
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        parts = [part for part in path_of(result.url).split("/") if part]
        return len(parts) == 1 and parts[0].lower() not in RESERVED
