from __future__ import annotations

from fastapi.testclient import TestClient

from app.errors import SearchUnavailableError
from app.main import app, get_prospect_service
from app.platforms.registry import get_adapters
from app.schemas import DiscoveryResponse, Prospect, QueryIntent, SocialLink


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


def test_request_id_is_echoed_and_generated() -> None:
    with TestClient(app) as client:
        echoed = client.get("/health", headers={"X-Request-ID": "test-request-123"})
        generated = client.get("/health")
    assert echoed.headers["X-Request-ID"] == "test-request-123"
    assert generated.headers["X-Request-ID"]


def test_docs_and_openapi_expose_all_routes() -> None:
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
    assert {"/health", "/platforms", "/validate", "/prospect-discovery"} <= set(schema["paths"])


def test_platforms_report_has_no_secrets() -> None:
    with TestClient(app) as client:
        body = client.get("/platforms").json()
    assert set(body) == {
        "llm_provider",
        "llm_model",
        "llm_configured",
        "tavily_configured",
        "platforms",
    }
    assert body["platforms"] == [adapter.name for adapter in get_adapters()]
    assert all(not str(value).startswith(("AIza", "tvly-", "gsk_")) for value in body.values())


class FakeQueryService:
    async def understand(self, query: str) -> QueryIntent:
        return QueryIntent(interest="Football", audience="Football lovers", city="Washington DC")


class FakeExtractor:
    @staticmethod
    def build_queries(intent: QueryIntent) -> list[str]:
        return ["site:linkedin.com football washington dc"]


class FakeValidationService:
    query = FakeQueryService()
    extractor = FakeExtractor()


def test_validate_endpoint_shows_plan_without_searching() -> None:
    app.dependency_overrides[get_prospect_service] = lambda: FakeValidationService()
    try:
        with TestClient(app) as client:
            response = client.post("/validate", json={"query": "Football lovers in Washington DC"})
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "Football lovers in Washington DC"
        assert body["intent"]["interest"] == "Football"
        assert body["queries"] == ["site:linkedin.com football washington dc"]
    finally:
        app.dependency_overrides.clear()
