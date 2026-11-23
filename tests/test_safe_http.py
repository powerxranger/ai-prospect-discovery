from __future__ import annotations

import httpx
import pytest

from app.services.safe_http import SafeHTTPClient


def _public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_private_url_is_never_requested(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, text="secret")

    fetcher = SafeHTTPClient(settings, _client(handler))
    assert await fetcher.get_text("http://169.254.169.254/latest/meta-data") is None
    assert called is False


async def test_public_redirect_is_followed(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/start"):
            return httpx.Response(302, headers={"Location": "https://public.example.com/end"})
        return httpx.Response(
            200, text="<html><body>John Smith</body></html>", headers={"Content-Type": "text/html"}
        )

    fetcher = SafeHTTPClient(settings, _client(handler))
    result = await fetcher.get_text("https://public.example.com/start")
    assert result is not None
    assert "John Smith" in result.text
    assert result.url.endswith("/end")


async def test_redirect_to_private_address_is_blocked(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    fetcher = SafeHTTPClient(settings, _client(handler))
    assert await fetcher.get_text("https://public.example.com/start") is None


async def test_non_html_content_is_rejected(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"key": "value"})

    fetcher = SafeHTTPClient(settings, _client(handler))
    assert await fetcher.get_text("https://public.example.com/data.json") is None


async def test_response_is_size_limited(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo", _public_dns)
    settings.safe_fetch_max_bytes = 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="a" * 5_000, headers={"Content-Type": "text/html"})

    fetcher = SafeHTTPClient(settings, _client(handler))
    result = await fetcher.get_text("https://public.example.com/large")
    assert result is not None
    assert len(result.text) <= 100
