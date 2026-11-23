from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, host_matches_any, path_of

DOMAINS = {"youtube.com", "youtu.be"}
PREFIXES = {"@", "channel", "c", "user"}


class YouTubeAdapter(PlatformAdapter):
    name = "YouTube"
    search_hint = "public creator and channel profiles"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'site:youtube.com "{focus}"' if focus else "site:youtube.com"
        if location:
            query += f' "{location}"'
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        parts = [part for part in path_of(result.url).split("/") if part]
        if not parts:
            return False
        if parts[0].startswith("@"):
            return len(parts) == 1 and len(parts[0]) > 1
        return parts[0] in PREFIXES and len(parts) >= 2
