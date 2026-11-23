from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, urlparse

from .validators import sanitize_text

GENERIC_NAME_TOKENS = {
    "about",
    "channel",
    "contact",
    "facebook",
    "home",
    "instagram",
    "linkedin",
    "login",
    "page",
    "pages",
    "posts",
    "profile",
    "profiles",
    "search",
    "threads",
    "tiktok",
    "twitter",
    "video",
    "videos",
    "watch",
    "x",
    "youtube",
}
SPLIT_RE = re.compile(
    r"\s*[|\u00b7\u2022\u2122]\s*|\s+[-\u2013\u2014]\s+|\s+on\s+LinkedIn\b",
    re.IGNORECASE,
)


def ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def normalize_name(value: str) -> str:
    folded = ascii_fold(value or "").lower()
    folded = re.sub(r"[^a-z0-9\s]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def normalize_handle(value: str) -> str:
    folded = ascii_fold(value or "").lower()
    folded = folded.lstrip("@").strip()
    return re.sub(r"[^a-z0-9._-]+", "", folded)


def plausible_name(value: str) -> bool:
    candidate = sanitize_text(value, 120)
    if not candidate or len(candidate) > 90:
        return False
    words = normalize_name(candidate).split()
    if not 1 <= len(words) <= 6:
        return False
    if any(word in GENERIC_NAME_TOKENS for word in words):
        return False
    letters = sum(char.isalpha() for char in candidate)
    return letters >= 2 and not candidate.lower().startswith("http")


def extract_name(title: str, snippet: str = "", url: str = "") -> str | None:
    """Take a name only from observed title/snippet text; never invent one."""
    for raw in (title, snippet):
        text = sanitize_text(raw or "", 300)
        if not text:
            continue
        first_part = SPLIT_RE.split(text)[0]
        first_part = re.split(r"\s*\(@", first_part, maxsplit=1)[0]
        first_part = re.split(r"\s+[-\u2013\u2014]\s+", first_part, maxsplit=1)[0]
        first_part = first_part.strip(" \"'.,:;")
        if plausible_name(first_part):
            return first_part
    return None


def extract_platform_handle(url: str, platform: str) -> str | None:
    parsed = urlparse(url or "")
    parts = [part for part in parsed.path.split("/") if part]

    if platform == "LinkedIn":
        for part in parts:
            if part in {"in", "pub"} and parts.index(part) + 1 < len(parts):
                return normalize_handle(parts[parts.index(part) + 1])
    elif platform == "X":
        if parts and parts[0] not in {"i", "intent", "search", "home", "explore", "share"}:
            return normalize_handle(parts[0])
    elif platform == "Instagram":
        if parts and parts[0] not in {"p", "reel", "reels", "explore", "accounts", "tv"}:
            return normalize_handle(parts[0])
    elif platform == "Threads":
        for part in parts:
            if part.startswith("@"):
                return normalize_handle(part)
    elif platform == "Facebook":
        if parts[0:1] == ["profile.php"]:
            return parse_qs(parsed.query).get("id", [None])[0]
        if parts and parts[0] not in {"search", "login", "groups", "pages", "people"}:
            return normalize_handle(parts[0])
    elif platform == "YouTube":
        if parts and parts[0] in {"@"}:
            return normalize_handle(parts[1]) if len(parts) > 1 else None
        if parts and parts[0] in {"channel", "c", "user"} and len(parts) > 1:
            return normalize_handle(parts[1])
        if parts and parts[0].startswith("@"):
            return normalize_handle(parts[0])
    elif platform == "Google":
        if parts:
            return normalize_handle(parts[-1])
    elif platform in {"WhatsApp", "Email"}:
        query = parse_qs(parsed.query)
        return query.get("phone", [None])[0] or (parts[0] if parts else None)
    return None


def location_label(city: str | None, state: str | None, country: str | None) -> str:
    pieces: list[str] = []
    for value in (city, state, country):
        clean = sanitize_text(value or "", 80)
        if clean and clean.lower() not in {piece.lower() for piece in pieces}:
            pieces.append(clean)
    return ", ".join(pieces) if pieces else "Location not published"


def evidence_text(*values: str | None, limit: int = 2_000) -> str:
    return sanitize_text(" ".join(value for value in values if value), limit)
