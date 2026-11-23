from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, host_matches_any, path_of

DOMAINS = {"linkedin.com"}


class LinkedInAdapter(PlatformAdapter):
    name = "LinkedIn"
    search_hint = "public professional profiles"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        base = f'site:linkedin.com/in "{focus}"' if focus else "site:linkedin.com/in"
        if location:
            base += f' "{location}"'
        return [base]

    def accepts(self, result: SearchResult) -> bool:
        if not host_matches_any(result.url, DOMAINS):
            return False
        parts = [part for part in path_of(result.url).split("/") if part]
        return len(parts) >= 2 and parts[0] in {"in", "pub", "company"}
