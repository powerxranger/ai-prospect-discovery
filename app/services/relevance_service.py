from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..schemas import Candidate, QueryIntent
from ..utils.normalizers import normalize_name, plausible_name
from ..utils.prompts import CANDIDATE_SYSTEM, CANDIDATE_USER, untrusted_block
from ..utils.validators import sanitize_text
from .llm_service import LLMService

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "and",
    "for",
    "from",
    "in",
    "into",
    "lovers",
    "near",
    "of",
    "owners",
    "the",
    "with",
}

GENERIC_PROFILE_TERMS = {
    "about",
    "accelerator",
    "agency",
    "all",
    "association",
    "best",
    "blog",
    "box",
    "caterer",
    "channel",
    "club",
    "collective",
    "community",
    "content",
    "contact",
    "creative",
    "directory",
    "digital",
    "events",
    "experts",
    "fans",
    "find",
    "fintech",
    "followers",
    "forum",
    "founder",
    "founders",
    "grounds",
    "group",
    "guide",
    "home",
    "incubator",
    "info",
    "investments",
    "labs",
    "leaders",
    "list",
    "login",
    "love",
    "luxury",
    "magazine",
    "management",
    "marketing",
    "match",
    "matches",
    "me",
    "media",
    "mentor",
    "mentorship",
    "mind",
    "network",
    "news",
    "notice",
    "number",
    "owners",
    "platform",
    "privacy",
    "pro",
    "profile",
    "profiles",
    "quality",
    "register",
    "reviews",
    "ranking",
    "rankings",
    "search",
    "services",
    "shop",
    "show",
    "social",
    "software",
    "sports",
    "stadium",
    "startup",
    "startups",
    "studio",
    "studios",
    "subscribers",
    "terms",
    "tips",
    "time",
    "top",
    "updates",
    "vlog",
    "venture",
    "ventures",
    "video",
    "videos",
    "watch",
    "website",
    "llc",
    "ltd",
    "inc",
    "co",
}


class LLMValidationCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0)
    name: str | None = None
    location: str | None = None
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    audience_match: bool = False
    location_match: bool = False


class LLMValidationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidates: list[LLMValidationCandidate] = Field(default_factory=list)


def _terms(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        word
        for word in sanitize_text(value, 200).lower().split()
        if len(word) > 2 and word not in STOP_WORDS and not word.isdigit()
    }


def _observed_text(candidate: Candidate) -> str:
    return sanitize_text(
        " ".join((candidate.name, candidate.title, candidate.snippet, candidate.evidence)),
        3_000,
    ).lower()


def _mentions(value: str | None, observed: str) -> bool:
    if not value:
        return False
    normalized = normalize_name(value)
    return bool(normalized) and normalized in normalize_name(observed)


def deterministic_score(candidate: Candidate, intent: QueryIntent) -> float:
    observed = _observed_text(candidate)
    interest_terms = _terms(intent.interest)
    audience_terms = _terms(intent.audience)
    topic_terms = interest_terms | audience_terms
    location_terms = _terms(intent.city) | _terms(intent.state) | _terms(intent.country)
    if any(token in {"dc", "d.c"} for token in _terms(intent.city)):
        location_terms.add("dc")

    topic_hits = sum(1 for term in topic_terms if term in observed)
    location_hits = sum(1 for term in location_terms if term in observed)

    score = 0.0
    if topic_hits:
        score += 0.45
    if location_hits:
        score += 0.30
    if plausible_name(candidate.name):
        score += 0.15
    if candidate.handles:
        score += 0.05
    if candidate.platform != "Google":
        score += 0.05

    if intents_location_expected(intent) and not location_hits:
        score -= 0.30
    if topic_terms and not topic_hits:
        score -= 0.35
    return max(0.0, min(1.0, score))


def intents_location_expected(intent: QueryIntent) -> bool:
    return bool(intent.city or intent.state or intent.country)


def _location_terms(intent: QueryIntent) -> set[str]:
    terms = _terms(intent.city) | _terms(intent.state) | _terms(intent.country)
    for variant in intent.location_variants:
        terms |= _terms(variant)
    city = normalize_name(intent.city or "")
    if city in {"washington dc", "washington d c"}:
        terms |= {"dc", "d c"}
    if city == "new york":
        terms.add("nyc")
    return terms


def _is_generic_or_echo_name(name: str, intent: QueryIntent) -> bool:
    """Reject SEO-style labels and names that merely echo the query."""
    if not plausible_name(name):
        return True
    words = normalize_name(name).split()
    if not words:
        return True

    topic_terms = _terms(intent.interest) | _terms(intent.audience)
    location_terms = _location_terms(intent)
    removable = topic_terms | location_terms | STOP_WORDS | GENERIC_PROFILE_TERMS
    distinctive = [word for word in words if word not in removable and not word.isdigit()]
    if not distinctive:
        return True

    name_terms = set(words)
    if topic_terms and topic_terms <= name_terms:
        primary_location = _terms(intent.city) | _terms(intent.country)
        if primary_location and primary_location <= name_terms:
            return True
    return False


class RelevanceService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def refine(
        self,
        candidates: list[Candidate],
        intent: QueryIntent,
    ) -> list[Candidate]:
        if not candidates:
            return []
        validated = await self._llm_validate(candidates, intent)
        results: list[Candidate] = []
        for candidate in candidates:
            observed = _observed_text(candidate)
            validated_item = validated.get(candidate_index(candidates, candidate))
            if validated_item is not None:
                self._apply_llm_data(candidate, validated_item, observed)
            score = deterministic_score(candidate, intent)
            if validated_item is not None:
                score = max(0.0, min(1.0, 0.6 * score + 0.4 * validated_item.relevance_score))
            candidate.relevance_score = round(score, 3)
            if score < 0.35:
                continue
            if not _terms(intent.interest) | _terms(intent.audience):
                continue
            if not any(
                term in observed for term in _terms(intent.interest) | _terms(intent.audience)
            ):
                continue
            if _is_generic_or_echo_name(candidate.name, intent):
                continue
            results.append(candidate)
        return results

    async def _llm_validate(
        self,
        candidates: list[Candidate],
        intent: QueryIntent,
    ) -> dict[int, LLMValidationCandidate]:
        blocks = "\n".join(
            untrusted_block(
                index,
                candidate.platform,
                candidate.url,
                candidate.title,
                candidate.snippet,
            )
            for index, candidate in enumerate(candidates)
        )
        prompt = CANDIDATE_USER.format(intent=intent.model_dump_json(), candidates=blocks)
        try:
            raw: dict[str, Any] = await self.llm.generate_json(CANDIDATE_SYSTEM, prompt)
            parsed = LLMValidationResponse.model_validate(raw)
        except Exception:
            logger.info("LLM candidate validation unavailable; using deterministic checks")
            return {}
        return {item.index: item for item in parsed.candidates if 0 <= item.index < len(candidates)}

    @staticmethod
    def _apply_llm_data(
        candidate: Candidate,
        item: LLMValidationCandidate,
        observed: str,
    ) -> None:
        if item.name and plausible_name(item.name) and _mentions(item.name, observed):
            candidate.name = sanitize_text(item.name, 120)
        if item.location:
            expected = candidate.location.lower()
            if _mentions(item.location, observed) or normalize_name(
                item.location
            ) in normalize_name(expected):
                candidate.location = sanitize_text(item.location, 160)
        if item.evidence and _mentions(item.evidence, observed):
            candidate.evidence = sanitize_text(item.evidence, 1_000)
        if not candidate.location:
            candidate.location = "Location not published"


def candidate_index(candidates: list[Candidate], candidate: Candidate) -> int:
    for index, item in enumerate(candidates):
        if item is candidate:
            return index
    return -1
