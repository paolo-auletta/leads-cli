from __future__ import annotations

from dataclasses import dataclass

from company_discovery.domain.models import NormalizedCandidate


KNOWN_NON_COMPANY_DOMAINS = frozenset(
    {
        "bbb.org",
        "bloomberg.com",
        "chamberofcommerce.com",
        "crunchbase.com",
        "facebook.com",
        "glassdoor.com",
        "instagram.com",
        "linkedin.com",
        "mapquest.com",
        "manta.com",
        "opencorporates.com",
        "pitchbook.com",
        "wikipedia.org",
        "yelp.com",
        "yellowpages.com",
        "youtube.com",
    }
)


@dataclass(frozen=True)
class HygieneResult:
    accepted: list[NormalizedCandidate]
    rejected: list[tuple[NormalizedCandidate, str]]


def filter_hygiene(candidates: list[NormalizedCandidate]) -> HygieneResult:
    accepted: list[NormalizedCandidate] = []
    rejected: list[tuple[NormalizedCandidate, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.domain in seen:
            rejected.append((candidate, "duplicate_domain"))
        elif candidate.domain in KNOWN_NON_COMPANY_DOMAINS:
            rejected.append((candidate, "known_non_company_domain"))
        elif not candidate.company_name.strip():
            rejected.append((candidate, "missing_company_name"))
        else:
            seen.add(candidate.domain)
            accepted.append(candidate)
    return HygieneResult(accepted=accepted, rejected=rejected)

