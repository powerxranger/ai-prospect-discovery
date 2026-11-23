from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, path_of

CONTACT_WORDS = ("contact", "email", "about", "team")


class EmailAdapter(PlatformAdapter):
    name = "Email"
    search_hint = "publicly published email addresses"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'"{focus}" "{location}" email contact'.replace('"" ', "").strip()
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        haystack = f"{result.title} {result.snippet} {path_of(result.url)}".lower()
        return (
            "email" in haystack
            or "contact" in haystack
            or any(word in haystack for word in CONTACT_WORDS)
        )
