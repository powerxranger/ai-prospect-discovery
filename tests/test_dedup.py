from __future__ import annotations

from app.schemas import SocialLink
from app.services.deduplication_service import DeduplicationService, should_merge
from tests.conftest import make_candidate


def test_same_person_across_platforms_is_merged() -> None:
    linkedin = make_candidate(
        platform="LinkedIn",
        url="https://www.linkedin.com/in/john-smith-football/",
        handles=["john-smith-football"],
    )
    instagram = make_candidate(
        platform="Instagram",
        url="https://www.instagram.com/john-smith-football/",
        handles=["john-smith-football"],
        score=0.7,
    )
    response = DeduplicationService().consolidate([linkedin, instagram], "football Washington DC")
    assert response.total_prospects == 1
    assert len(response.prospects[0].social_link) == 2
    assert {item.platform for item in response.prospects[0].social_link} == {
        "LinkedIn",
        "Instagram",
    }


def test_similar_names_with_different_handles_are_not_merged() -> None:
    first = make_candidate(
        platform="LinkedIn",
        url="https://www.linkedin.com/in/john-smith-dc/",
        handles=["john-smith-dc"],
    )
    second = make_candidate(
        platform="Instagram",
        url="https://www.instagram.com/john.smith.77/",
        handles=["john.smith.77"],
    )
    assert should_merge(first, second) is False
    response = DeduplicationService().consolidate([first, second], "football Washington DC")
    assert response.total_prospects == 2


def test_shared_public_email_merges_profiles() -> None:
    first = make_candidate(url="https://www.linkedin.com/in/john-smith-football/")
    second = make_candidate(
        platform="X",
        url="https://x.com/jsmithfootball",
        handles=["jsmithfootball"],
    )
    email = SocialLink(platform="Email", link="mailto:john@example.com")
    first.contact_links.append(email)
    second.contact_links.append(email)
    assert should_merge(first, second) is True
    response = DeduplicationService().consolidate([first, second], "football Washington DC")
    assert response.total_prospects == 1
    assert any(item.platform == "Email" for item in response.prospects[0].social_link)


def test_response_has_exact_shape() -> None:
    response = DeduplicationService().consolidate([make_candidate()], "football Washington DC")
    assert set(response.model_dump()) == {"success", "query", "total_prospects", "prospects"}
    prospect = response.prospects[0].model_dump()
    assert set(prospect) == {"name", "location", "social_link"}
    assert set(prospect["social_link"][0]) == {"platform", "link"}
    assert response.success is True
    assert response.total_prospects == 1


def test_empty_input_returns_empty_response() -> None:
    response = DeduplicationService().consolidate([], "query")
    assert response.prospects == []
    assert response.total_prospects == 0
