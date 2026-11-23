from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, has_query, host_matches_any, path_of

DOMAINS = {"facebook.com", "m.facebook.com"}
RESERVED = {"search", "login", "groups", "events", "photo", "photos", "permalink", "people", "help"}


class FacebookAdapter(PlatformAdapter):
    name = "Facebook"
    search_hint = "public profiles and pages"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'site:facebook.com "{focus}"' if focus else "site:facebook.com"
        if location:
            query += f' "{location}"'
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        parts = [part for part in path_of(result.url).split("/") if part]
        if parts and parts[0] == "profile.php":
            return has_query(result.url, "id")
        if not parts or parts[0].lower() in RESERVED:
            return False
        return len(parts) <= 3
