from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils.validators import sanitize_text, validate_email_address

PlatformName = Literal[
    "Google",
    "LinkedIn",
    "X",
    "YouTube",
    "Instagram",
    "WhatsApp",
    "Facebook",
    "Email",
    "Threads",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DiscoveryRequest(StrictModel):
    query: str = Field(min_length=3, max_length=300)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = sanitize_text(value, 300)
        if len(cleaned) < 3:
            raise ValueError("Query must contain at least 3 characters.")
        return cleaned


class QueryIntent(StrictModel):
    interest: str
    audience: str
    city: str | None = None
    state: str | None = None
    country: str | None = None
    target_type: Literal["individual", "business"] = "individual"
    search_terms: list[str] = Field(default_factory=list, max_length=8)
    location_variants: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("interest", "audience")
    @classmethod
    def non_empty(cls, value: str) -> str:
        cleaned = sanitize_text(value, 120)
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("city", "state", "country")
    @classmethod
    def clean_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = sanitize_text(value, 80)
        return cleaned or None

    @field_validator("search_terms", "location_variants")
    @classmethod
    def clean_terms(cls, values: list[str]) -> list[str]:
        return [sanitize_text(value, 120) for value in values if sanitize_text(value, 120)]

    @model_validator(mode="after")
    def fill_defaults(self) -> QueryIntent:
        if not self.search_terms:
            self.search_terms = [self.audience, self.interest]
        if not self.location_variants:
            self.location_variants = [
                value for value in (self.city, self.state, self.country) if value
            ]
        return self


class SocialLink(StrictModel):
    platform: PlatformName
    link: str = Field(max_length=2_000)

    @field_validator("link")
    @classmethod
    def valid_link(cls, value: str) -> str:
        cleaned = sanitize_text(value, 2_000)
        if cleaned.startswith("mailto:"):
            if validate_email_address(cleaned.removeprefix("mailto:")):
                return cleaned
            raise ValueError("invalid email link")
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("link must be a public http(s) URL or mailto")
        if parsed.username or parsed.password:
            raise ValueError("embedded credentials are not allowed")
        return cleaned


class Prospect(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="Location not published", max_length=160)
    social_link: list[SocialLink] = Field(min_length=1, max_length=12)


class DiscoveryResponse(StrictModel):
    success: bool = True
    query: str
    total_prospects: int = Field(default=0, ge=0)
    prospects: list[Prospect]

    @model_validator(mode="after")
    def sync_total(self) -> DiscoveryResponse:
        self.total_prospects = len(self.prospects)
        return self


class Candidate(StrictModel):
    name: str = ""
    platform: PlatformName
    url: str
    title: str = ""
    snippet: str = ""
    evidence: str = ""
    location: str = "Location not published"
    handles: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    fetched_text: str | None = None
    contact_links: list[SocialLink] = Field(default_factory=list)
    source_query: str = ""
