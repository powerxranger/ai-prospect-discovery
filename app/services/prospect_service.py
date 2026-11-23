from __future__ import annotations

import logging

from ..config import Settings
from ..schemas import DiscoveryResponse
from ..utils.validators import sanitize_text
from .cache import TTLCache
from .contact_service import ContactService
from .deduplication_service import DeduplicationService
from .llm_service import LLMService
from .profile_extractor import ProfileExtractor
from .query_service import QueryService
from .relevance_service import RelevanceService
from .safe_http import SafeHTTPClient
from .search_service import SearchService

logger = logging.getLogger(__name__)


class ProspectService:
    """Orchestrates intent parsing, discovery, validation and consolidation."""

    def __init__(
        self,
        settings: Settings,
        cache: TTLCache | None = None,
        llm: LLMService | None = None,
        search: SearchService | None = None,
        fetcher: SafeHTTPClient | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)
        self.llm = llm or LLMService(settings)
        self.query = QueryService(self.llm, self.cache)
        self.search = search or SearchService(settings, self.cache)
        self.fetcher = fetcher or SafeHTTPClient(settings)
        self.extractor = ProfileExtractor(settings)
        self.relevance = RelevanceService(self.llm)
        self.contacts = ContactService(settings, self.fetcher)
        self.deduplication = DeduplicationService()

    async def discover(self, query: str) -> DiscoveryResponse:
        clean_query = sanitize_text(query, 300)
        key = TTLCache.key({"discovery": clean_query})
        cached = await self.cache.get(key)
        if cached is not None:
            return DiscoveryResponse.model_validate(cached)

        intent = await self.query.understand(clean_query)
        logger.info(
            "Parsed intent: interest=%s city=%s country=%s target=%s",
            intent.interest,
            intent.city,
            intent.country,
            intent.target_type,
        )
        queries = self.extractor.build_queries(intent)
        logger.info("Running %s platform discovery queries", len(queries))
        results = await self.search.search_many(queries)
        logger.info("Collected %s search results", len(results))
        candidates = self.extractor.build_candidates(results, intent)
        logger.info("Accepted %s profile-shaped candidates", len(candidates))
        relevant = await self.relevance.refine(candidates, intent)
        logger.info("Kept %s relevant candidates", len(relevant))
        enriched = await self.contacts.enrich(relevant, intent)
        response = self.deduplication.consolidate(enriched, clean_query)
        validated = DiscoveryResponse.model_validate(response.model_dump())
        await self.cache.set(key, validated.model_dump())
        logger.info("Returning %s consolidated prospects", validated.total_prospects)
        return validated

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.search.aclose()
        await self.fetcher.aclose()
