from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..config import Settings
from ..schemas import Candidate, QueryIntent, SocialLink
from ..utils.normalizers import normalize_handle, normalize_name
from ..utils.validators import (
    extract_emails,
    extract_phone_numbers,
    normalize_phone_number,
    sanitize_text,
)
from .safe_http import SafeHTTPClient

logger = logging.getLogger(__name__)

DEFAULT_REGION_BY_COUNTRY = {
    "USA": "US",
    "UK": "GB",
    "India": "IN",
    "UAE": "AE",
    "Canada": "CA",
    "Australia": "AU",
}
STRIP_TAGS = ("script", "style", "nav", "footer", "header", "aside", "form", "noscript")
WA_LINK_RE = re.compile(r"wa\.me/(\d{7,15})", re.IGNORECASE)


def visible_text_and_links(html: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(list(STRIP_TAGS)):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    links = [str(node.get("href", "")) for node in soup.find_all("a", href=True)]
    return sanitize_text(text, 50_000), links


def _is_associated(candidate: Candidate, page_text: str) -> bool:
    normalized_page = normalize_name(page_text)
    words = [word for word in normalize_name(candidate.name).split() if len(word) > 2]
    if any(word in normalized_page for word in words[:2]):
        return True
    handle = normalize_handle(candidate.handles[0]) if candidate.handles else ""
    return bool(handle) and len(handle) > 2 and handle in normalized_page


def _phone_from_link(link: str, default_region: str | None) -> str | None:
    parsed = urlparse(link)
    host = (parsed.hostname or "").lower().rstrip(".")
    if link.lower().startswith("tel:"):
        return normalize_phone_number(link[4:], default_region)
    if host == "wa.me":
        parts = [part for part in parsed.path.split("/") if part]
        return normalize_phone_number(parts[0], default_region) if parts else None
    if host in {"api.whatsapp.com", "web.whatsapp.com"}:
        phone = parse_qs(parsed.query).get("phone", [None])[0]
        return normalize_phone_number(phone, default_region) if phone else None
    match = WA_LINK_RE.search(link)
    return normalize_phone_number(match.group(1), default_region) if match else None


class ContactService:
    """Extracts only publicly published contact details from candidate pages."""

    def __init__(
        self,
        settings: Settings,
        fetcher: SafeHTTPClient,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher

    async def enrich(
        self,
        candidates: list[Candidate],
        intent: QueryIntent,
    ) -> list[Candidate]:
        if not candidates or self.settings.max_profile_fetches == 0:
            return candidates
        region = DEFAULT_REGION_BY_COUNTRY.get(intent.country or "")
        ordered = sorted(candidates, key=lambda item: item.relevance_score, reverse=True)
        for candidate in ordered[: self.settings.max_profile_fetches]:
            fetched = await self.fetcher.get_text(candidate.url)
            if fetched is None:
                continue
            candidate.fetched_text = fetched.text
            page_text, links = visible_text_and_links(fetched.text)
            combined = f"{candidate.snippet} {page_text}"
            if not _is_associated(candidate, combined):
                continue
            await self._add_contacts(candidate, combined, links, region)
        return candidates

    async def _add_contacts(
        self,
        candidate: Candidate,
        page_text: str,
        links: list[str],
        default_region: str | None,
    ) -> None:
        emails: list[str] = []
        for email in extract_emails(page_text):
            if email not in emails:
                emails.append(email)
        for link in links:
            if link.lower().startswith("mailto:"):
                email_values = extract_emails(link.removeprefix("mailto:"))
                if email_values and email_values[0] not in emails:
                    emails.append(email_values[0])

        phones: list[str] = []
        for phone in extract_phone_numbers(page_text, default_region):
            if phone not in phones:
                phones.append(phone)
        for link in links:
            phone_value = _phone_from_link(link, default_region)
            if phone_value and phone_value not in phones:
                phones.append(phone_value)

        additions: list[SocialLink] = []
        for email in emails[:2]:
            additions.append(SocialLink(platform="Email", link=f"mailto:{email}"))
        for phone in phones[:2]:
            additions.append(
                SocialLink(platform="WhatsApp", link=f"https://wa.me/{phone.lstrip('+')}")
            )
        existing = {(item.platform, item.link) for item in candidate.contact_links}
        for item in additions:
            if (item.platform, item.link) not in existing:
                candidate.contact_links.append(item)
