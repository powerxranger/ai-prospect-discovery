from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel

from ..config import Settings
from ..utils.validators import is_public_http_url, sanitize_text

logger = logging.getLogger(__name__)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class SafeFetchResult(BaseModel):
    url: str
    text: str
    content_type: str


class SafeHTTPClient:
    """Fetches public pages with strict URL, redirect, size and type limits."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ProspectDiscovery/1.0)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_text(self, url: str) -> SafeFetchResult | None:
        current = url
        for _ in range(self.settings.max_redirects + 1):
            safe, reason = is_public_http_url(current)
            if not safe:
                logger.info("Rejected unsafe fetch target: %s", reason)
                return None
            try:
                async with self._client.stream("GET", current) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(str(response.url), location)
                        continue
                    if not 200 <= response.status_code < 300:
                        logger.info("Profile fetch returned HTTP %s", response.status_code)
                        return None
                    content_type = response.headers.get("content-type", "").split(";")[0].lower()
                    if not any(allowed in content_type for allowed in ALLOWED_CONTENT_TYPES):
                        logger.info("Profile fetch rejected content type")
                        return None
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes(8_192):
                        buffer.extend(chunk)
                        if len(buffer) >= self.settings.safe_fetch_max_bytes:
                            break
                    encoding = response.encoding or "utf-8"
                    text = bytes(buffer[: self.settings.safe_fetch_max_bytes]).decode(
                        encoding, errors="replace"
                    )
                    return SafeFetchResult(
                        url=str(response.url),
                        text=sanitize_text(text, self.settings.safe_fetch_max_chars),
                        content_type=content_type,
                    )
            except httpx.HTTPError:
                logger.info("Profile fetch failed")
                return None
        logger.info("Too many redirects while fetching profile")
        return None
