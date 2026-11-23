from __future__ import annotations

from ..schemas import Candidate, DiscoveryResponse, Prospect, SocialLink
from ..utils.normalizers import normalize_handle, normalize_name, plausible_name
from ..utils.validators import normalize_url

PLATFORM_ORDER = {
    "Google": 0,
    "LinkedIn": 1,
    "X": 2,
    "YouTube": 3,
    "Instagram": 4,
    "Facebook": 5,
    "WhatsApp": 6,
    "Email": 7,
    "Threads": 8,
}
DEFAULT_LOCATION = "Location not published"


def name_key(candidate: Candidate) -> str:
    return normalize_name(candidate.name)


def handle_keys(candidate: Candidate) -> set[str]:
    return {normalize_handle(value) for value in candidate.handles if normalize_handle(value)}


def email_keys(candidate: Candidate) -> set[str]:
    return {
        item.link.removeprefix("mailto:").lower()
        for item in candidate.contact_links
        if item.platform == "Email"
    }


def profile_key(candidate: Candidate) -> str:
    return normalize_url(candidate.url)


def should_merge(left: Candidate, right: Candidate) -> bool:
    if profile_key(left) == profile_key(right):
        return True
    if not plausible_name(left.name) or not plausible_name(right.name):
        return False
    if name_key(left) != name_key(right):
        return False
    if handle_keys(left) & handle_keys(right):
        return True
    return bool(email_keys(left) & email_keys(right))


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def link_key(link: SocialLink) -> str:
    if link.link.startswith("mailto:"):
        return f"mailto:{link.link.removeprefix('mailto:').lower()}"
    return normalize_url(link.link)


class DeduplicationService:
    def consolidate(
        self,
        candidates: list[Candidate],
        query: str,
    ) -> DiscoveryResponse:
        eligible = [item for item in candidates if plausible_name(item.name)]
        if not eligible:
            return DiscoveryResponse(query=query, prospects=[])

        groups: dict[int, list[Candidate]] = {}
        finder = UnionFind(len(eligible))
        for left in range(len(eligible)):
            for right in range(left + 1, len(eligible)):
                if should_merge(eligible[left], eligible[right]):
                    finder.union(left, right)
        for index, candidate in enumerate(eligible):
            groups.setdefault(finder.find(index), []).append(candidate)

        prospects: list[Prospect] = []
        for group in groups.values():
            group.sort(key=lambda item: (item.relevance_score, len(item.evidence)), reverse=True)
            best = group[0]
            location = DEFAULT_LOCATION
            for candidate in group:
                if candidate.location and candidate.location != DEFAULT_LOCATION:
                    location = candidate.location
                    break
            links: dict[str, SocialLink] = {}
            for candidate in group:
                all_links = [SocialLink(platform=candidate.platform, link=candidate.url)]
                all_links.extend(candidate.contact_links)
                for link in all_links:
                    links.setdefault(link_key(link), link)
            ordered = sorted(
                links.values(),
                key=lambda link: (PLATFORM_ORDER.get(link.platform, 99), link.link),
            )[:12]
            if not ordered:
                continue
            prospects.append(
                Prospect(
                    name=best.name,
                    location=location or DEFAULT_LOCATION,
                    social_link=ordered,
                )
            )
        prospects.sort(key=lambda item: item.name.lower())
        return DiscoveryResponse(query=query, prospects=prospects)
