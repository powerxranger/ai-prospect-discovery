from __future__ import annotations

from app.schemas import QueryIntent
from app.services.contact_service import ContactService, _phone_from_link, visible_text_and_links
from tests.conftest import FakeFetcher, make_candidate


def intent() -> QueryIntent:
    return QueryIntent(interest="Football", audience="Football lovers", country="USA")


def test_visible_text_strips_scripts() -> None:
    html = "<html><script>alert(1)</script><body><p>John Smith</p></body></html>"
    text, _ = visible_text_and_links(html)
    assert "alert" not in text
    assert "John Smith" in text


def test_phone_from_whatsapp_link() -> None:
    assert _phone_from_link("https://wa.me/12025550123", "US") == "+12025550123"
    assert _phone_from_link("tel:+12025550123", "US") == "+12025550123"
    assert _phone_from_link("https://example.com", "US") is None


async def test_contact_details_are_extracted_from_associated_page(settings) -> None:
    url = "https://johnsmith.example.com/contact"
    html = """
    <html><body>
      <h1>John Smith</h1>
      <p>Football coach in Washington DC. Email john@johnsmith.example.com.</p>
      <p>Call +1 202 555 0123 or message https://wa.me/12025550123</p>
      <a href="mailto:john@johnsmith.example.com">Email</a>
    </body></html>
    """
    fetcher = FakeFetcher({url: html})
    service = ContactService(settings, fetcher)
    candidate = make_candidate(url=url)
    result = (await service.enrich([candidate], intent()))[0]
    links = [(item.platform, item.link) for item in result.contact_links]
    assert ("Email", "mailto:john@johnsmith.example.com") in links
    assert ("WhatsApp", "https://wa.me/12025550123") in links


async def test_unassociated_page_does_not_add_contacts(settings) -> None:
    url = "https://other.example.com/contact"
    html = "<html><body><p>Someone else can be reached at other@example.com.</p></body></html>"
    fetcher = FakeFetcher({url: html})
    service = ContactService(settings, fetcher)
    candidate = make_candidate(url=url)
    candidate.snippet = "Public profile."
    candidate.evidence = "Public profile."
    result = (await service.enrich([candidate], intent()))[0]
    assert result.contact_links == []


async def test_no_profile_fetches_when_disabled(settings) -> None:
    settings.max_profile_fetches = 0
    fetcher = FakeFetcher({})
    service = ContactService(settings, fetcher)
    candidate = make_candidate()
    assert (await service.enrich([candidate], intent()))[0].contact_links == []
    assert fetcher.calls == []
