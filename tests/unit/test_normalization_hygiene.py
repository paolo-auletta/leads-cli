from company_discovery.domain.models import ExaSearchResult
from company_discovery.services.hygiene import filter_hygiene
from company_discovery.services.normalization import canonical_domain, normalize_results


def result(url: str, title: str, query: str = "builders") -> ExaSearchResult:
    return ExaSearchResult(query=query, position=1, title=title, url=url, text="Texas builder")


def test_canonical_domain_handles_subdomains_and_compound_suffixes() -> None:
    assert canonical_domain("https://www.acme.com/about") == "acme.com"
    assert canonical_domain("https://careers.acme.co.uk/jobs") == "acme.co.uk"
    assert canonical_domain("mailto:test@example.com") is None
    assert canonical_domain("localhost:8000") is None


def test_results_are_deduped_by_company_domain_and_sightings_are_merged() -> None:
    candidates = normalize_results(
        [
            result("https://www.acme.com", "Acme Builders | Home", "one"),
            result("https://acme.com/about", "About Acme", "two"),
            result("https://beta.com", "Beta Construction - Texas"),
        ]
    )
    assert [candidate.domain for candidate in candidates] == ["acme.com", "beta.com"]
    assert candidates[0].company_name == "Acme Builders"
    assert len(candidates[0].sightings) == 2


def test_hygiene_only_removes_known_non_company_domains() -> None:
    candidates = normalize_results(
        [result("https://linkedin.com/company/acme", "Acme"), result("https://acme.com", "Acme")]
    )
    filtered = filter_hygiene(candidates)
    assert [item.domain for item in filtered.accepted] == ["acme.com"]
    assert filtered.rejected[0][1] == "known_non_company_domain"


def test_exa_company_entity_fields_are_normalized() -> None:
    item = result("https://acme.com", "Fallback Name")
    item.raw = {
        "entities": [
            {
                "type": "company",
                "properties": {
                    "name": "Acme Structured",
                    "workforce": {"total": 42},
                    "headquarters": {"country": "United States"},
                },
            }
        ]
    }
    candidate = normalize_results([item])[0]
    assert candidate.company_name == "Acme Structured"
    assert (candidate.employee_min, candidate.employee_max) == (42, 42)
    assert candidate.country == "US"
