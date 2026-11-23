from __future__ import annotations

from fastapi.testclient import TestClient

from app.errors import SearchUnavailableError
from app.main import app, get_prospect_service
from app.schemas import DiscoveryResponse, Prospect, SocialLink


class FakeProspectService:
    def __init__(
        self, response: DiscoveryResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []

    async def discover(self, query: str) -> DiscoveryResponse:
        self.queries.append(query)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def sample_response() -> DiscoveryResponse:
    return DiscoveryResponse(
        query="Football lovers in Washington DC in USA",
        prospects=[
            Prospect(
                name="John Smith",
                location="Washington DC, USA",
                social_link=[
                    SocialLink(platform="LinkedIn", link="https://www.linkedin.com/in/john-smith/"),
                    SocialLink(platform="Email", link="mailto:john@example.com"),
                ],
            )
        ],
    )


def test_prospect_discovery_endpoint_returns_exact_json() -> None:
    fake = FakeProspectService(sample_response())
    app.dependency_overrides[get_prospect_service] = lambda: fake
    try:
        with TestClient(app) as client:
            response = client.post(
                "/prospect-discovery",
                json={"query": "Football lovers in Washington DC in USA"},
            )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"success", "query", "total_prospects", "prospects"}
        assert body["success"] is True
        assert body["total_prospects"] == 1
        assert set(body["prospects"][0]) == {"name", "location", "social_link"}
        assert fake.queries == ["Football lovers in Washington DC in USA"]
    finally:
        app.dependency_overrides.clear()


def test_invalid_query_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post("/prospect-discovery", json={"query": "ab"})
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_search_failure_is_structured() -> None:
    fake = FakeProspectService(error=SearchUnavailableError())
    app.dependency_overrides[get_prospect_service] = lambda: fake
    try:
        with TestClient(app) as client:
            response = client.post("/prospect-discovery", json={"query": "Football lovers in DC"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SEARCH_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
