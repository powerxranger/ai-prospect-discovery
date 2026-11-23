from __future__ import annotations

import pytest

from app.utils.validators import (
    extract_emails,
    extract_phone_numbers,
    is_public_http_url,
    normalize_phone_number,
    sanitize_text,
    validate_email_address,
)


def _public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _private_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("10.0.0.5", 443))]


def test_public_url_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)
    assert is_public_http_url("https://example.com/profile/john") == (True, "ok")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:4000",
        "http://169.254.169.254/latest/meta-data",
        "http://10.1.2.3",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
        "http://example.com:8080/",
        "https://service.internal/",
    ],
)
def test_unsafe_urls_are_rejected(url: str) -> None:
    safe, _ = is_public_http_url(url, resolve_dns=False)
    assert safe is False


def test_private_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _private_dns)
    safe, reason = is_public_http_url("https://example.com/")
    assert safe is False
    assert "private" in reason


def test_email_validation() -> None:
    assert validate_email_address("John.Smith@Example.com") == "John.Smith@example.com"
    assert validate_email_address("not-an-email") is None
    assert validate_email_address("noreply@linkedin.com") is None


def test_extract_emails_from_text() -> None:
    assert extract_emails("Reach me at john@example.com or jane@example.org.") == [
        "john@example.com",
        "jane@example.org",
    ]


def test_phone_normalization() -> None:
    assert normalize_phone_number("+1 (202) 555-0123") == "+12025550123"
    assert normalize_phone_number("123") is None
    assert extract_phone_numbers("Call +1 202 555 0123 today") == ["+12025550123"]


def test_sanitize_text_removes_control_characters() -> None:
    assert sanitize_text("hello\x00\nworld") == "hello world"


def test_sanitize_text_removes_invisible_format_characters() -> None:
    assert sanitize_text("Afran\u200f Khan\u200e") == "Afran Khan"
