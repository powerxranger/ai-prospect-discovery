from __future__ import annotations

import logging

from ..config import Settings
from ..platforms.registry import get_adapters
from ..schemas import Candidate, QueryIntent
from ..utils.validators import normalize_url
from .search_service import SearchResult

logger = logging.getLogger(__name__)


class ProfileExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adapters = get_adapters()

    def build_queries(self, intent: QueryIntent) -> list[str]:
        queries: list[str] = []
        for adapter in self.adapters:
            try:
                queries.extend(adapter.build_queries(intent))
            except Exception:
                logger.info("Query build failed for %s", adapter.name)
        return list(dict.fromkeys(queries))

    def build_candidates(
        self,
        results: list[SearchResult],
        intent: QueryIntent,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for result in results:
            key = normalize_url(result.url)
            if key in seen:
                continue
            seen.add(key)
            for adapter in self.adapters:
                try:
                    if not adapter.accepts(result):
                        continue
                    candidate = adapter.extract(result, intent)
                except Exception:
                    logger.info("Extraction failed for %s", adapter.name)
                    continue
                if candidate is not None:
                    candidates.append(candidate)
                    break
            if len(candidates) >= self.settings.max_candidates:
                break
        return candidates
