from __future__ import annotations

from dataclasses import dataclass

from company_discovery.db.repository import MemoryRecord
from company_discovery.domain.models import FitVerdict
from company_discovery.domain.spec import CompanySearchSpec, NoveltyMode


@dataclass(frozen=True)
class SkippedMemoryRecord:
    record: MemoryRecord
    reason: str


@dataclass(frozen=True)
class MemoryScanResult:
    matched: int
    reusable: list[MemoryRecord]
    recheck: list[MemoryRecord]
    skipped: list[SkippedMemoryRecord]


class MemoryMatcher:
    def scan(self, spec: CompanySearchSpec, records: list[MemoryRecord]) -> MemoryScanResult:
        if spec.novelty_mode == NoveltyMode.ONLY_NEW:
            return MemoryScanResult(
                matched=0,
                reusable=[],
                recheck=[],
                skipped=[
                    SkippedMemoryRecord(record, "memory_disabled_only_new") for record in records
                ],
            )

        reusable: list[MemoryRecord] = []
        recheck: list[MemoryRecord] = []
        skipped: list[SkippedMemoryRecord] = []
        for record in records:
            mismatch = self._hard_mismatch(spec, record)
            if mismatch:
                skipped.append(SkippedMemoryRecord(record, mismatch))
                continue
            if (
                record.latest_fit == FitVerdict.GOOD.value
                and record.latest_evaluation is not None
                and not self._requires_recheck(spec, record)
            ):
                reusable.append(record)
            else:
                recheck.append(record)

        return MemoryScanResult(
            matched=len(reusable) + len(recheck),
            reusable=reusable,
            recheck=recheck,
            skipped=skipped,
        )

    @staticmethod
    def _hard_mismatch(spec: CompanySearchSpec, record: MemoryRecord) -> str | None:
        candidate = record.candidate
        previous = record.latest_spec
        reason_codes = set(record.latest_reason_codes)
        if previous is not None:
            previous_target = (
                record.latest_evaluation.target_vertical
                if record.latest_evaluation is not None
                else None
            )
            same_vertical = previous_target == spec.vertical.key or (
                len(previous.verticals) == 1 and previous.verticals[0] == spec.vertical
            )
            if "vertical_mismatch" in reason_codes and same_vertical:
                return "prior_vertical_mismatch_same_spec"
            if (
                "geography_mismatch" in reason_codes
                and previous.geography == spec.geography
            ):
                return "prior_geography_mismatch_same_spec"
            if "size_mismatch" in reason_codes and previous.company_size == spec.company_size:
                return "prior_size_mismatch_same_spec"
            exclusion_codes = {
                "excluded_ownership",
                "excluded_keyword",
                "excluded_company_pattern",
            }
            if reason_codes & exclusion_codes and previous.exclude == spec.exclude:
                return "prior_exclusion_same_spec"
        if spec.novelty_mode == NoveltyMode.UNUSED_MEMORY and record.ever_selected:
            return "previously_selected"
        if candidate.vertical and candidate.vertical != spec.vertical.key:
            return "vertical_mismatch"
        if candidate.country and candidate.country.upper() != spec.geography.country:
            return "country_mismatch"
        if spec.geography.states and candidate.state and candidate.state.upper() not in spec.geography.states:
            return "state_mismatch"
        size = spec.company_size
        if (
            size.employee_min is not None
            and candidate.employee_max is not None
            and candidate.employee_max < size.employee_min
        ):
            return "size_below_minimum"
        if (
            size.employee_max is not None
            and candidate.employee_min is not None
            and candidate.employee_min > size.employee_max
        ):
            return "size_above_maximum"
        if (
            candidate.ownership_type
            and candidate.ownership_type.lower() in spec.exclude.ownership_types
        ):
            return "excluded_ownership"
        searchable = " ".join(
            [candidate.company_name]
            + [sighting.title for sighting in candidate.sightings]
            + [sighting.text or "" for sighting in candidate.sightings]
        ).lower()
        if any(keyword in searchable for keyword in spec.exclude.keywords):
            return "excluded_keyword"
        return None

    @staticmethod
    def _requires_recheck(spec: CompanySearchSpec, record: MemoryRecord) -> bool:
        candidate = record.candidate
        if candidate.vertical is None or candidate.country is None:
            return True
        if spec.geography.states and candidate.state is None:
            return True
        if not spec.company_size.is_unbounded and (
            candidate.employee_min is None or candidate.employee_max is None
        ):
            return True

        previous = record.latest_spec
        if spec.include.keywords or spec.include.subtypes:
            if previous is None or previous.include != spec.include:
                return True
        has_custom_exclusions = any(
            (
                spec.exclude.keywords,
                spec.exclude.ownership_types,
                spec.exclude.company_patterns,
            )
        )
        if has_custom_exclusions and (previous is None or previous.exclude != spec.exclude):
            return True
        return False
