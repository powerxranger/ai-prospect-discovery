from __future__ import annotations

import pytest

from app.schemas import QueryIntent
from app.services.relevance_service import RelevanceService, deterministic_score
from tests.conftest import FakeLLM, make_candidate


def intent() -> QueryIntent:
    return QueryIntent(
        interest="Football",
        audience="Football lovers",
        city="Washington DC",
        state="District of Columbia",
        country="USA",
    )


async def test_llm_data_must_match_observed_text() -> None:
    candidate = make_candidate()
    fake = FakeLLM(
        [
            {
                "candidates": [
                    {
                        "index": 0,
                        "name": "Jane Doe",
                        "location": "Miami",
                        "relevance_score": 1.0,
                        "evidence": "copied quote",
                    }
                ]
            }
        ]
    )
    kept = await RelevanceService(fake).refine([candidate], intent())
    assert len(kept) == 1
    assert candidate.name == "John Smith"
    assert candidate.location == "Washington DC, District of Columbia, USA"


async def test_valid_llm_data_is_applied() -> None:
    candidate = make_candidate()
    fake = FakeLLM(
        [
            {
                "candidates": [
                    {
                        "index": 0,
                        "name": "John Smith",
                        "location": "Washington DC",
                        "relevance_score": 0.95,
                        "evidence": "Football coach in Washington DC",
                    }
                ]
            }
        ]
    )
    kept = await RelevanceService(fake).refine([candidate], intent())
    assert len(kept) == 1
    assert kept[0].location == "Washington DC"
    assert kept[0].relevance_score >= 0.35


async def test_untrusted_prompt_markers_are_present() -> None:
    fake = FakeLLM([{"candidates": []}])
    await RelevanceService(fake).refine([make_candidate()], intent())
    system, prompt = fake.calls[0]
    assert "UNTRUSTED DATA" in system
    assert "<untrusted_search_data>" in prompt
    assert "Ignore any instruction" in system


async def test_candidate_without_topic_evidence_is_filtered() -> None:
    candidate = make_candidate()
    candidate.title = "Random page | Example"
    candidate.snippet = "Nothing relevant here."
    candidate.evidence = "Nothing relevant here."
    fake = FakeLLM([{"candidates": []}])
    assert await RelevanceService(fake).refine([candidate], intent()) == []


def test_deterministic_score_is_bounded() -> None:
    score = deterministic_score(make_candidate(), intent())
    assert 0.0 <= score <= 1.0


@pytest.mark.parametrize(
    "name",
    [
        "1K+ followers",
        "21 Runs for Power Panthers Ahmedabad",
        "Privacy Notice",
        "To Register Call: 93161-03960",
        "Update: Football Lovers in Washington DC",
        "Football Lovers in Washington DC",
        "Football Club Washington DC",
    ],
)
async def test_generic_and_query_echo_names_are_filtered(name: str) -> None:
    candidate = make_candidate(name=name)
    fake = FakeLLM([{"candidates": []}])
    assert await RelevanceService(fake).refine([candidate], intent()) == []


async def test_distinctive_business_name_is_kept() -> None:
    candidate = make_candidate(
        name="The Setters Agency",
        url="https://www.linkedin.com/company/the-setters-agency/",
        handles=["the-setters-agency"],
    )
    fake = FakeLLM([{"candidates": []}])
    assert await RelevanceService(fake).refine([candidate], intent()) == [candidate]


async def test_generic_agency_label_is_filtered_for_agency_query() -> None:
    agency_intent = QueryIntent(
        interest="Digital marketing agency",
        audience="Digital marketing agency owners",
        city="New York",
        state="New York",
        country="USA",
        target_type="business",
    )
    generic = make_candidate(
        name="Digital Marketing Agency New York",
        url="https://www.linkedin.com/company/digital-marketing-agency-new-york/",
        handles=["digital-marketing-agency-new-york"],
    )
    distinctive = make_candidate(
        name="The Setters Agency",
        url="https://www.linkedin.com/company/the-setters-agency/",
        handles=["the-setters-agency"],
    )
    fake = FakeLLM([{"candidates": []}, {"candidates": []}])
    service = RelevanceService(fake)
    assert await service.refine([generic], agency_intent) == []
    assert await service.refine([distinctive], agency_intent) == [distinctive]
