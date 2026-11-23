from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from urllib.parse import urlparse, urlunparse

import phonenumbers
from email_validator import EmailNotValidError, validate_email

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FORMAT_CHARS = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "fc00::/7",
        "fe80::/10",
        "::1/128",
    )
)
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".localdomain")
PLATFORM_EMAIL_DOMAINS = {
    "linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "instagram.com",
    "facebook.com",
    "threads.net",
    "threads.com",
    "tavily.com",
    "google.com",
}


def sanitize_text(value: str, max_chars: int = 4000) -> str:
    """Remove control/invisible format characters and cap length before using text."""
    cleaned = FORMAT_CHARS.sub("", value or "")
    cleaned = CONTROL_CHARS.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    ):
        return True
    return any(ip in network for network in BLOCKED_NETWORKS)


def is_public_http_url(url: str, *, resolve_dns: bool = True) -> tuple[bool, str]:
    """Validate a URL and reject private/internal targets (SSRF protection)."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False, "malformed URL"

    if parsed.scheme not in {"http", "https"}:
        return False, "scheme must be http or https"
    if parsed.username or parsed.password:
        return False, "embedded credentials are not allowed"
    if not parsed.hostname:
        return False, "hostname is required"
    if parsed.port not in (None, 80, 443):
        return False, "port is not allowed"

    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "metadata", "metadata.google.internal"}:
        return False, "internal hostname"
    if any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        return False, "internal hostname"

    if len(host) > 253 or any(len(label) > 63 for label in host.split(".")):
        return False, "invalid hostname"
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return False, "invalid hostname"
    if "." not in host and host != "localhost":
        return False, "hostname must include a TLD"

    literal_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    with contextlib.suppress(ValueError):
        literal_ip = ipaddress.ip_address(host)
    if literal_ip is not None and _ip_is_blocked(literal_ip):
        return False, "private or reserved address"

    if resolve_dns and literal_ip is None:
        try:
            infos = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (socket.gaierror, OSError):
            return False, "DNS resolution failed"
        if not infos:
            return False, "DNS resolution failed"
        for info in infos:
            address = info[4][0]
            try:
                resolved_ip = ipaddress.ip_address(address)
            except ValueError:
                return False, "invalid resolved address"
            if _ip_is_blocked(resolved_ip):
                return False, "private or resolved address"

    return True, "ok"


def normalize_url(url: str) -> str:
    """Canonicalize a safe URL for deduplication without changing its target."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", "", ""))


def validate_email_address(value: str, *, check_deliverability: bool = False) -> str | None:
    candidate = value.strip().strip("<>").strip()
    if not candidate or len(candidate) > 254:
        return None
    try:
        result = validate_email(candidate, check_deliverability=check_deliverability)
    except EmailNotValidError:
        return None
    domain = result.domain.lower()
    if domain in PLATFORM_EMAIL_DOMAINS:
        return None
    return result.normalized


def normalize_phone_number(value: str, default_region: str | None = None) -> str | None:
    candidate = re.sub(r"[^\d+]", "", value or "")
    if not candidate or len(candidate) > 18:
        return None
    try:
        number = phonenumbers.parse(candidate, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for match in EMAIL_RE.findall(sanitize_text(text, 50_000)):
        valid = validate_email_address(match)
        if valid and valid not in found:
            found.append(valid)
    return found


def extract_phone_numbers(text: str, default_region: str | None = None) -> list[str]:
    found: list[str] = []
    for match in PHONE_RE.findall(sanitize_text(text, 50_000)):
        valid = normalize_phone_number(match, default_region)
        if valid and valid not in found:
            found.append(valid)
    return found


def host_matches(url: str, domains: set[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in domains)
