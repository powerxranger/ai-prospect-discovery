from __future__ import annotations

import logging
import re
from typing import Any, Literal

from ..errors import LLMConfigurationError
from ..schemas import QueryIntent
from ..utils.prompts import INTENT_SYSTEM, INTENT_USER
from ..utils.validators import sanitize_text
from .cache import TTLCache
from .llm_service import LLMService

logger = logging.getLogger(__name__)

COUNTRY_TOKENS = {
    "usa": "USA",
    "united states": "USA",
    "united states of america": "USA",
    "uk": "UK",
    "united kingdom": "UK",
    "england": "UK",
    "india": "India",
    "uae": "UAE",
    "united arab emirates": "UAE",
    "canada": "Canada",
    "australia": "Australia",
    "germany": "Germany",
    "france": "France",
    "singapore": "Singapore",
}
STATE_BY_CITY = {
    "washington dc": "District of Columbia",
    "washington d.c.": "District of Columbia",
    "new york": "New York",
    "ahmedabad": "Gujarat",
    "dubai": "Dubai",
    "london": "England",
}
BUSINESS_TERMS = (
    "owner",
    "founder",
    "agency",
    "company",
    "business",
    "brand",
    "restaurant",
    "startup",
    "ceo",
    "shop",
    "store",
)


def _split_country(location: str) -> tuple[str, str | None]:
    lowered = location.lower().strip()
    for token, label in sorted(COUNTRY_TOKENS.items(), key=lambda item: -len(item[0])):
        pattern = rf"(?:^|[\s,]+){re.escape(token)}(?:$|[\s,]+)"
        match = re.search(pattern, lowered)
        if match:
            city = location[: match.start()].strip(" ,-")
            return city, label
    return location.strip(" ,-"), None


def fallback_intent(query: str) -> QueryIntent:
    """Generic text parser used only when the LLM is unavailable."""
    cleaned = sanitize_text(query, 300)
    lowered = cleaned.lower()
    matches = list(re.finditer(r"\bin\s+([^,]+?)(?=\s+in\s+|$)", lowered))
    chunks = [cleaned[match.start(1) : match.end(1)].strip(" ,-") for match in matches]
    audience = cleaned
    city: str | None = None
    state: str | None = None
    country: str | None = None
    if chunks:
        audience = cleaned[: matches[0].start()].strip(" ,-") or cleaned
        city_chunk, chunk_country = _split_country(chunks[0])
        city = city_chunk or None
        country = chunk_country
        if len(chunks) > 1:
            _, second_country = _split_country(chunks[-1])
            country = second_country or country
        state = STATE_BY_CITY.get((city or "").lower())
    if not audience:
        audience = cleaned
    interest = (
        re.sub(
            r"\b(lovers?|fans?|enthusiasts?|owners?|founders?|in\s+.*)$",
            "",
            audience,
            flags=re.IGNORECASE,
        ).strip(" ,-")
        or audience
    )
    target_type: Literal["individual", "business"] = (
        "business" if any(term in lowered for term in BUSINESS_TERMS) else "individual"
    )
    location_values = [value for value in (city, state, country) if value]
    return QueryIntent(
        interest=interest,
        audience=audience,
        city=city,
        state=state,
        country=country,
        target_type=target_type,
        search_terms=[audience, interest, *location_values],
        location_variants=location_values,
    )


class QueryService:
    def __init__(self, llm: LLMService, cache: TTLCache) -> None:
        self.llm = llm
        self.cache = cache

    async def understand(self, query: str) -> QueryIntent:
        cleaned = sanitize_text(query, 300)
        key = TTLCache.key(cleaned)
        cached = await self.cache.get(key)
        if cached is not None:
            return QueryIntent.model_validate(cached)

        try:
            raw = await self.llm.generate_json(INTENT_SYSTEM, INTENT_USER.format(query=cleaned))
            intent = QueryIntent.model_validate(self._coerce(raw))
            await self.cache.set(key, intent.model_dump())
            return intent
        except LLMConfigurationError as exc:
            logger.info("Using deterministic intent parser: %s", exc.client_message)
        except Exception as exc:
            logger.warning("LLM intent failed; using deterministic parser: %s", type(exc).__name__)
        intent = fallback_intent(cleaned)
        await self.cache.set(key, intent.model_dump())
        return intent

    @staticmethod
    def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
        payload = dict(raw)
        location = payload.pop("location", None)
        if isinstance(location, dict):
            payload.setdefault("city", location.get("city"))
            payload.setdefault("state", location.get("state"))
            payload.setdefault("country", location.get("country"))
        target = payload.get("target_type")
        if target not in {"individual", "business"}:
            payload["target_type"] = "individual"
        return payload


__all__ = ["QueryService", "fallback_intent"]
