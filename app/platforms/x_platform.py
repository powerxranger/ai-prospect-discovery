from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, host_matches_any, path_of

DOMAINS = {"x.com", "twitter.com"}
RESERVED = {"i", "intent", "search", "home", "explore", "share", "status", "settings", "messages"}


class XAdapter(PlatformAdapter):
    name = "X"
    search_hint = "public user profiles"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = (
            f'(site:x.com OR site:twitter.com) "{focus}"'
            if focus
            else "(site:x.com OR site:twitter.com)"
        )
        if location:
            query += f' "{location}"'
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        parts = [part for part in path_of(result.url).split("/") if part]
        return len(parts) == 1 and parts[0].lower() not in RESERVED and not parts[0].isdigit()
