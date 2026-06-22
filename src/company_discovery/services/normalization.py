from __future__ import annotations

import re
from collections import OrderedDict
from datetime import UTC, datetime
from urllib.parse import urlparse

import tldextract

from company_discovery.domain.models import ExaSearchResult, NormalizedCandidate, SourceSighting


_extract_domain = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
_TITLE_SUFFIX = re.compile(r"\s+[|\-\u2013\u2014]\s+.*$")


def canonical_domain(url: str) -> str | None:
    value = url.strip()
    if not value:
        return None
    if ":" in value and "://" not in value:
        host, _, port = value.partition(":")
        if not ("." in host and port.isdigit()):
            return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    extracted = _extract_domain(parsed.hostname.lower())
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}"


def candidate_name(title: str, domain: str) -> str:
    cleaned = _TITLE_SUFFIX.sub("", title).strip()
    if cleaned:
        return cleaned
    return domain.split(".", maxsplit=1)[0].replace("-", " ").title()


def normalize_results(results: list[ExaSearchResult]) -> list[NormalizedCandidate]:
    by_domain: OrderedDict[str, NormalizedCandidate] = OrderedDict()
    now = datetime.now(UTC)
    for result in results:
        domain = canonical_domain(result.url)
        if domain is None:
            continue
        sighting = SourceSighting(
            query=result.query,
            url=result.url,
            title=result.title,
            text=result.text,
            exa_id=result.exa_id,
            raw=result.raw,
        )
        existing = by_domain.get(domain)
        if existing is None:
            entity = _company_entity(result.raw)
            properties = entity.get("properties", {}) if entity else {}
            workforce = properties.get("workforce") or {}
            headquarters = properties.get("headquarters") or {}
            employee_total = workforce.get("total")
            if not isinstance(employee_total, int) or employee_total < 1:
                employee_total = None
            country = _country_code(headquarters.get("country"))
            by_domain[domain] = NormalizedCandidate(
                company_name=properties.get("name") or candidate_name(result.title, domain),
                domain=domain,
                dedupe_key=domain,
                country=country,
                employee_min=employee_total,
                employee_max=employee_total,
                sightings=[sighting],
                first_seen_at=now,
                last_seen_at=now,
            )
        elif all(item.url != sighting.url for item in existing.sightings):
            existing.sightings.append(sighting)
    return list(by_domain.values())


def _company_entity(raw: dict) -> dict:
    entities = raw.get("entities")
    if not isinstance(entities, list):
        return {}
    for entity in entities:
        if isinstance(entity, dict) and entity.get("type") in {None, "company"}:
            return entity
    return {}


def _country_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if normalized in {"UNITED STATES", "UNITED STATES OF AMERICA", "USA"}:
        return "US"
    return normalized if len(normalized) == 2 else None
