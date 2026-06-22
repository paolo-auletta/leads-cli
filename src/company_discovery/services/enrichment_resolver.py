from __future__ import annotations

import re
from datetime import UTC, datetime

from company_discovery.domain.models import (
    EnrichmentExtraction,
    IndependenceFact,
    IndependenceStatus,
    LocationFact,
    PhoneFact,
)


US_STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper()
    return US_STATE_NAMES.get(cleaned, cleaned if len(cleaned) == 2 else None)


def resolve_phone(extraction: EnrichmentExtraction, source: str) -> PhoneFact | None:
    if not extraction.phones:
        return None
    preferred = next(
        (phone for phone in extraction.phones if "fax" not in (phone.label or "").lower()),
        None,
    )
    if preferred is None:
        return None
    digits = re.sub(r"\D", "", preferred.value)
    if len(digits) == 10:
        normalized = f"+1{digits}"
        display = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):
        normalized = f"+{digits}"
        display = f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    elif 8 <= len(digits) <= 15:
        normalized = f"+{digits}"
        display = preferred.value.strip()
    else:
        return None
    return PhoneFact(
        value=normalized,
        display_value=display,
        source=source,
        source_url=preferred.source_url,
    )


def resolve_location(
    extraction: EnrichmentExtraction,
    target_state: str | None,
    source: str,
) -> tuple[LocationFact | None, bool]:
    if not extraction.locations:
        return None, False
    expected = normalize_state(target_state)
    normalized = [(location, normalize_state(location.state)) for location in extraction.locations]
    chosen = next((location for location, state in normalized if expected and state == expected), None)
    geography_conflict = bool(expected and chosen is None)
    if chosen is None and expected is None:
        chosen = next(
            (location for location in extraction.locations if "head" in (location.label or "").lower()),
            extraction.locations[0],
        )
    if chosen is None:
        return None, geography_conflict
    return (
        LocationFact(
            street_address=chosen.street_address,
            city=chosen.city,
            state=normalize_state(chosen.state) or chosen.state,
            zip=chosen.zip,
            country=chosen.country,
            source=source,
            source_url=chosen.source_url,
        ),
        False,
    )


def resolve_independence(extraction: EnrichmentExtraction) -> IndependenceFact:
    negative = {"franchise", "parent", "subsidiary", "division", "acquired"}
    positive = {"independent_explicit", "family_owned", "locally_owned"}
    kinds = {signal.kind for signal in extraction.ownership_signals}
    if kinds & negative:
        status = IndependenceStatus.NO
    elif kinds & positive:
        status = IndependenceStatus.YES
    else:
        status = IndependenceStatus.UNKNOWN
    return IndependenceFact(
        status=status,
        evidence=[signal.statement for signal in extraction.ownership_signals],
        source_urls=list(dict.fromkeys(signal.source_url for signal in extraction.ownership_signals)),
        observed_at=datetime.now(UTC),
    )
