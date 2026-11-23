from __future__ import annotations

import pytest

from app.services.query_service import QueryService, fallback_intent
from tests.conftest import FakeLLM


async def test_llm_intent_is_validated(settings, cache) -> None:
    fake = FakeLLM(
        [
            {
                "interest": "Football",
                "audience": "Football lovers",
                "location": {
                    "city": "Washington DC",
                    "state": "District of Columbia",
                    "country": "USA",
                },
                "target_type": "individual",
            }
        ]
    )
    service = QueryService(fake, cache)
    intent = await service.understand("Football lovers in Washington DC in USA")
    assert intent.interest == "Football"
    assert intent.city == "Washington DC"
    assert intent.state == "District of Columbia"
    assert intent.country == "USA"
    assert intent.target_type == "individual"
    assert intent.search_terms


@pytest.mark.parametrize(
    ("query", "interest", "city", "country", "target_type"),
    [
        (
            "Football lovers in Washington DC in USA",
            "Football",
            "Washington DC",
            "USA",
            "individual",
        ),
        (
            "Digital marketing agency owners in New York USA",
            "Digital marketing agency",
            "New York",
            "USA",
            "business",
        ),
        ("Startup founders in London UK", "Startup", "London", "UK", "business"),
        ("Cricket lovers in Ahmedabad India", "Cricket", "Ahmedabad", "India", "individual"),
        ("Restaurant owners in Dubai UAE", "Restaurant", "Dubai", "UAE", "business"),
    ],
)
def test_fallback_intent_is_dynamic(query, interest, city, country, target_type) -> None:
    intent = fallback_intent(query)
    assert intent.interest == interest
    assert intent.city == city
    assert intent.country == country
    assert intent.target_type == target_type


async def test_query_understanding_is_cached(settings, cache) -> None:
    fake = FakeLLM([{"interest": "Cricket", "audience": "Cricket lovers"}])
    service = QueryService(fake, cache)
    first = await service.understand("Cricket lovers in Ahmedabad India")
    second = await service.understand("Cricket lovers in Ahmedabad India")
    assert first == second
    assert len(fake.calls) == 1
