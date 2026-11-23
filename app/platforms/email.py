from __future__ import annotations

from ..schemas import QueryIntent
from ..services.search_service import SearchResult
from .base import PlatformAdapter, host_matches_any, path_of

CONTACT_WORDS = ("contact", "email", "about", "team")
SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "threads.com",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "whatsapp.com",
    "x.com",
    "youtube.com",
    "youtu.be",
}
NON_CONTACT_PATHS = {
    "event",
    "events",
    "explore",
    "groups",
    "login",
    "p",
    "post",
    "posts",
    "reel",
    "reels",
    "search",
    "video",
    "videos",
    "watch",
}


class EmailAdapter(PlatformAdapter):
    name = "Email"
    search_hint = "publicly published email addresses"

    def build_queries(self, intent: QueryIntent) -> list[str]:
        focus, location = self.query_parts(intent)
        query = f'"{focus}" "{location}" email contact'.replace('"" ', "").strip()
        return [query]

    def accepts(self, result: SearchResult) -> bool:
        if host_matches_any(result.url, SOCIAL_DOMAINS):
            return False
        parts = [part.lower() for part in path_of(result.url).split("/") if part]
        if any(part in NON_CONTACT_PATHS for part in parts):
            return False
        haystack = f"{result.title} {result.snippet} {path_of(result.url)}".lower()
        return any(word in haystack for word in CONTACT_WORDS)
