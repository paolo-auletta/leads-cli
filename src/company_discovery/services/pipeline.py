from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from company_discovery.adapters.protocols import CompanySearchProvider
from company_discovery.db.repository import DiscoveryRepository, MemoryRecord
from company_discovery.domain.models import (
    CandidateBucket,
    CandidateEvaluation,
    BucketedCandidate,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    NormalizedCandidate,
    RunResult,
    RunSummary,
)
from company_discovery.domain.spec import BalanceMode, CompanySearchSpec, NoveltyMode, VerticalSpec
from company_discovery.reports.exporter import ArtifactExporter
from company_discovery.services.evaluator import CandidateEvaluator
from company_discovery.services.hygiene import filter_hygiene
from company_discovery.services.memory import MemoryMatcher
from company_discovery.services.normalization import normalize_results
from company_discovery.services.progress import NullProgressReporter, ProgressReporter
from company_discovery.services.query_planner import QueryPlanner


@dataclass
class EvaluatedCandidate:
    candidate_id: int
    candidate: NormalizedCandidate
    evaluation: CandidateEvaluation
    source: str
    target_vertical: str


@dataclass(frozen=True)
class ExternalCandidate:
    candidate: NormalizedCandidate
    lane_spec: CompanySearchSpec


class DiscoveryPipeline:
    def __init__(
        self,
        *,
        repository: DiscoveryRepository,
        exporter: ArtifactExporter,
        query_planner: QueryPlanner | None = None,
        evaluator: CandidateEvaluator | None = None,
        search_provider: CompanySearchProvider | None = None,
        memory_matcher: MemoryMatcher | None = None,
        results_per_query: int = 25,
    ) -> None:
        self._repository = repository
        self._exporter = exporter
        self._query_planner = query_planner
        self._evaluator = evaluator
        self._search_provider = search_provider
        self._memory_matcher = memory_matcher or MemoryMatcher()
        self._results_per_query = results_per_query

    def discover(
        self,
        spec: CompanySearchSpec,
        *,
        source_spec_path: Path | None = None,
        progress: ProgressReporter | None = None,
    ) -> RunResult:
        reporter = progress or NullProgressReporter()
        run_id = self._repository.create_run(
            spec,
            str(source_spec_path.resolve()) if source_spec_path else None,
        )
        try:
            return self._run(run_id, spec, reporter)
        except Exception as exc:
            self._repository.fail_run(run_id, exc)
            raise

    def _run(
        self,
        run_id: str,
        spec: CompanySearchSpec,
        reporter: ProgressReporter,
    ) -> RunResult:
        summary = RunSummary()
        evaluated: list[EvaluatedCandidate] = []
        seen_domains: set[str] = set()
        quotas = spec.vertical_quotas
        lanes = [spec.lane_spec(vertical, quotas[vertical.key]) for vertical in spec.verticals]
        memory_trace: list[dict[str, object]] = []

        reporter.stage(1, 5, "Spec", "spec")
        reporter.info(self._spec_summary(spec))
        for condition in spec.missing_constraints:
            reporter.info(condition)

        reporter.stage(2, 5, "Memory Scan", "memory")
        records = self._repository.memory_records()
        known_domains = {record.candidate.domain for record in records}
        previously_selected_domains = {
            record.candidate.domain for record in records if record.ever_selected
        }
        excluded_external_domains = (
            known_domains
            if spec.novelty_mode == NoveltyMode.ONLY_NEW
            else previously_selected_domains
            if spec.novelty_mode == NoveltyMode.UNUSED_MEMORY
            else set()
        )
        if spec.novelty_mode == NoveltyMode.ONLY_NEW:
            reporter.info(
                f"Memory reuse disabled; {len(known_domains)} known domains will be excluded "
                "from external results"
            )
        else:
            reporter.info(f"Scanning {len(records)} saved companies")
        for lane in lanes:
            vertical = lane.vertical
            if spec.novelty_mode == NoveltyMode.ONLY_NEW:
                memory_trace.append(
                    {
                        "vertical": {"key": vertical.key, "label": vertical.label},
                        "target_count": lane.count,
                        "filter": self._memory_filter_summary(lane),
                        "mode": "bypassed",
                        "matched": 0,
                        "reused": [],
                        "rechecked": [],
                        "skipped": [],
                        "external_domains_excluded": [],
                    }
                )
                continue
            reporter.info(
                f"Lane {vertical.label} (target {lane.count}): "
                f"{self._memory_filter_summary(lane)}"
            )
            memory = self._memory_matcher.scan(lane, records)
            summary.memory_matched += memory.matched
            summary.memory_skipped += len(memory.skipped)
            lane_target_total = (
                lane.count + lane.reserve_count
                if spec.balance_mode == BalanceMode.STRICT
                else spec.count + spec.reserve_count
            )
            reusable = [
                record for record in memory.reusable if record.candidate.domain not in seen_domains
            ][:lane_target_total]
            for record in reusable:
                evaluated.append(self._reuse(record, vertical))
                seen_domains.add(record.candidate.domain)
            summary.memory_reused += len(reusable)

            reusable_good = sum(
                item.evaluation.fit == FitVerdict.GOOD
                and item.target_vertical == vertical.key
                for item in evaluated
            )
            recheck_capacity = max(0, lane.count - len(reusable)) if reusable_good < lane.count else 0
            rechecks = [
                record for record in memory.recheck if record.candidate.domain not in seen_domains
            ][:recheck_capacity]
            if rechecks:
                evaluator = self._require_evaluator()
                reporter.info(f"Re-evaluating {len(rechecks)} uncertain {vertical.label} companies")
                for index, record in enumerate(rechecks, start=1):
                    evaluation = evaluator.evaluate(lane, record.candidate).model_copy(
                        update={"target_vertical": vertical.key}
                    )
                    evaluated.append(
                        EvaluatedCandidate(
                            candidate_id=record.candidate_id,
                            candidate=record.candidate,
                            evaluation=evaluation,
                            source="memory_recheck",
                            target_vertical=vertical.key,
                        )
                    )
                    seen_domains.add(record.candidate.domain)
                    rolling = self._bucket_counts(evaluated, spec)
                    reporter.evaluation(
                        index,
                        len(rechecks),
                        rolling[CandidateBucket.SELECTED],
                        rolling[CandidateBucket.RESERVE],
                        rolling[CandidateBucket.REJECTED],
                        f"{vertical.label} memory recheck {record.candidate.domain}: {evaluation.fit.value}",
                    )
            summary.memory_rechecked += len(rechecks)
            memory_trace.append(
                {
                    "vertical": {"key": vertical.key, "label": vertical.label},
                    "target_count": lane.count,
                    "filter": self._memory_filter_summary(lane),
                    "matched": memory.matched,
                    "reused": [
                        {
                            "domain": record.candidate.domain,
                            "company_name": record.candidate.company_name,
                            "fit": record.latest_fit,
                            "ever_selected": record.ever_selected,
                        }
                        for record in reusable
                    ],
                    "rechecked": [
                        {
                            "domain": record.candidate.domain,
                            "company_name": record.candidate.company_name,
                        }
                        for record in rechecks
                    ],
                    "external_domains_excluded": [],
                    "skipped": [
                        {
                            "domain": skipped.record.candidate.domain,
                            "company_name": skipped.record.candidate.company_name,
                            "reason": skipped.reason,
                        }
                        for skipped in memory.skipped
                    ],
                }
            )
            reporter.info(
                f"{vertical.label}: matched {memory.matched}; reused {len(reusable)}; "
                f"rechecked {len(rechecks)}"
            )
            for skipped in memory.skipped:
                reporter.detail(
                    f"{vertical.label} skipped {skipped.record.candidate.domain}: {skipped.reason}"
                )

        lane_gaps = {
            lane.vertical.key: max(
                0,
                lane.count
                - sum(
                    item.evaluation.fit == FitVerdict.GOOD
                    and item.target_vertical == lane.vertical.key
                    for item in evaluated
                ),
            )
            for lane in lanes
        }
        summary.external_gap = sum(lane_gaps.values())
        queries: list[str] = []

        reporter.stage(3, 5, "External Search", "external")
        external_candidates: list[ExternalCandidate] = []
        hygiene_rejections: list[EvaluatedCandidate] = []
        if summary.external_gap == 0:
            reporter.info("Memory satisfied the requested company count; Exa was not called")
        else:
            planner = self._require_query_planner()
            provider = self._require_search_provider()
            query_number = 0
            for lane in lanes:
                gap = lane_gaps[lane.vertical.key]
                if gap == 0:
                    reporter.info(f"{lane.vertical.label}: memory complete; external search skipped")
                    continue
                reporter.info(
                    f"{lane.vertical.label}: gap {gap}; generating a dedicated Exa query plan"
                )
                plan = planner.plan(lane, gap)
                lane_raw_results = []
                for lane_index, query in enumerate(plan.queries, start=1):
                    query_number += 1
                    queries.append(query)
                    query_id = self._repository.add_query(
                        run_id, query_number, query, f"[{lane.vertical.key}] {plan.rationale}"
                    )
                    results = provider.search(
                        query,
                        country=lane.geography.country,
                        num_results=self._results_per_search(lane),
                    )
                    self._repository.save_query_results(
                        run_id, query_id, results, provider.last_cost_dollars
                    )
                    lane_raw_results.extend(results)
                    reporter.query(lane_index, len(plan.queries), query, len(lane_raw_results))
                summary.raw_results += len(lane_raw_results)
                normalized = [
                    candidate
                    for candidate in normalize_results(lane_raw_results)
                    if candidate.domain not in seen_domains
                ]
                if excluded_external_domains:
                    rediscovered = [
                        candidate
                        for candidate in normalized
                        if candidate.domain in excluded_external_domains
                    ]
                    normalized = [
                        candidate
                        for candidate in normalized
                        if candidate.domain not in excluded_external_domains
                    ]
                    trace = next(
                        item
                        for item in memory_trace
                        if item["vertical"]["key"] == lane.vertical.key
                    )
                    trace["external_domains_excluded"] = [
                        {
                            "domain": candidate.domain,
                            "company_name": candidate.company_name,
                            "reason": (
                                "already_known"
                                if spec.novelty_mode == NoveltyMode.ONLY_NEW
                                else "previously_selected"
                            ),
                        }
                        for candidate in rediscovered
                    ]
                    if rediscovered:
                        reporter.info(
                            f"{lane.vertical.label}: excluded {len(rediscovered)} domains under "
                            f"the {spec.novelty_mode.value} policy"
                        )
                summary.unique_candidates += len(normalized)
                seen_domains.update(candidate.domain for candidate in normalized)
                hygiene = filter_hygiene(normalized)
                summary.hygiene_rejected += len(hygiene.rejected)
                external_candidates.extend(
                    ExternalCandidate(candidate=candidate, lane_spec=lane)
                    for candidate in hygiene.accepted
                )
                for candidate, reason in hygiene.rejected:
                    candidate_id = self._repository.upsert_candidate(candidate)
                    hygiene_rejections.append(
                        EvaluatedCandidate(
                            candidate_id=candidate_id,
                            candidate=candidate,
                            evaluation=self._hygiene_evaluation(
                                candidate, reason, lane.vertical.key
                            ),
                            source="hygiene",
                            target_vertical=lane.vertical.key,
                        )
                    )
                reporter.info(
                    f"{lane.vertical.label}: {len(lane_raw_results)} raw; "
                    f"{len(normalized)} unique; {len(hygiene.accepted)} passed hygiene"
                )
            summary.queries_generated = len(queries)

        reporter.stage(4, 5, "Evaluation", "evaluation")
        total_to_evaluate = len(external_candidates)
        if external_candidates:
            evaluator = self._require_evaluator()
            for index, work in enumerate(external_candidates, start=1):
                candidate = work.candidate
                vertical = work.lane_spec.vertical
                candidate_id = self._repository.upsert_candidate(candidate)
                evaluation = evaluator.evaluate(work.lane_spec, candidate).model_copy(
                    update={"target_vertical": vertical.key}
                )
                evaluated.append(
                    EvaluatedCandidate(
                        candidate_id=candidate_id,
                        candidate=candidate,
                        evaluation=evaluation,
                        source="exa",
                        target_vertical=vertical.key,
                    )
                )
                rolling = self._bucket_counts(evaluated, spec)
                reporter.evaluation(
                    index,
                    total_to_evaluate,
                    rolling[CandidateBucket.SELECTED],
                    rolling[CandidateBucket.RESERVE],
                    rolling[CandidateBucket.REJECTED],
                    f"{vertical.label} / {candidate.company_name}: {evaluation.fit.value}",
                )
        evaluated.extend(hygiene_rejections)
        if not external_candidates:
            reporter.info("No new external candidates required evaluation")

        bucketed = self._assign_buckets(evaluated, spec)
        for item, bucket in bucketed:
            self._repository.record_evaluation(
                run_id,
                item.candidate_id,
                item.evaluation,
                bucket,
                item.source,
            )
        counts = self._count_assigned(bucketed)
        summary.selected = counts[CandidateBucket.SELECTED]
        summary.reserve = counts[CandidateBucket.RESERVE]
        summary.rejected = counts[CandidateBucket.REJECTED]

        reporter.stage(5, 5, "Save + Export", "save")
        reporter.info("Writing run artifacts")
        payload = self._repository.get_run(run_id)
        payload["memory_trace"] = memory_trace
        payload["status"] = "completed"
        artifact_paths = self._exporter.export(payload, summary)
        self._repository.complete_run(run_id, summary, artifact_paths)
        reporter.info(f"Saved run {run_id}")
        return RunResult(
            run_id=run_id,
            summary=summary,
            queries=queries,
            candidates=[
                BucketedCandidate(
                    candidate=item.candidate,
                    evaluation=item.evaluation,
                    bucket=bucket,
                    source=item.source,
                    target_vertical=item.target_vertical,
                )
                for item, bucket in bucketed
            ],
            artifact_paths=artifact_paths,
        )

    @staticmethod
    def _reuse(record: MemoryRecord, vertical: VerticalSpec) -> EvaluatedCandidate:
        if record.latest_evaluation is None:
            raise ValueError("reusable memory record has no evaluation")
        prior = record.latest_evaluation
        evaluation = prior.model_copy(
            update={
                "reason": f"Reused from company memory. Prior evaluation: {prior.reason}",
                "reason_codes": list(dict.fromkeys(["memory_reuse", *prior.reason_codes])),
                "target_vertical": vertical.key,
            }
        )
        return EvaluatedCandidate(
            candidate_id=record.candidate_id,
            candidate=record.candidate,
            evaluation=evaluation,
            source="memory",
            target_vertical=vertical.key,
        )

    @staticmethod
    def _hygiene_evaluation(
        candidate: NormalizedCandidate, reason: str, target_vertical: str
    ) -> CandidateEvaluation:
        return CandidateEvaluation(
            company_name=candidate.company_name,
            domain=candidate.domain,
            fit=FitVerdict.BAD,
            vertical_match=MatchVerdict.UNKNOWN,
            geography_match=MatchVerdict.UNKNOWN,
            size_match=MatchVerdict.UNKNOWN,
            excluded=ExclusionVerdict.YES,
            reason=f"Rejected by deterministic hygiene: {reason}.",
            reason_codes=[reason],
            evidence=[candidate.domain],
            inferred_vertical=None,
            inferred_country=None,
            inferred_state=None,
            inferred_employee_min=None,
            inferred_employee_max=None,
            inferred_ownership_type=None,
            target_vertical=target_vertical,
        )

    @staticmethod
    def _assign_buckets(
        items: list[EvaluatedCandidate],
        spec: CompanySearchSpec,
        *,
        annotate: bool = True,
    ) -> list[tuple[EvaluatedCandidate, CandidateBucket]]:
        selected_indices = DiscoveryPipeline._balanced_indices(
            items,
            [index for index, item in enumerate(items) if item.evaluation.fit == FitVerdict.GOOD],
            spec.count,
            spec,
        )
        reserve_candidates = [
            index
            for index, item in enumerate(items)
            if index not in selected_indices
            and item.evaluation.fit in {FitVerdict.GOOD, FitVerdict.POSSIBLE}
        ]
        reserve_indices = DiscoveryPipeline._balanced_indices(
            items, reserve_candidates, spec.reserve_count, spec
        )

        assigned: list[tuple[EvaluatedCandidate, CandidateBucket]] = []
        for index, item in enumerate(items):
            if index in selected_indices:
                bucket = CandidateBucket.SELECTED
            elif index in reserve_indices:
                bucket = CandidateBucket.RESERVE
            else:
                bucket = CandidateBucket.REJECTED
                if annotate and item.evaluation.fit in {FitVerdict.GOOD, FitVerdict.POSSIBLE}:
                    item.evaluation = item.evaluation.model_copy(
                        update={
                            "reason": f"{item.evaluation.reason} Not included because run capacity was full.",
                            "reason_codes": list(
                                dict.fromkeys([*item.evaluation.reason_codes, "capacity_full"])
                            ),
                        }
                    )
            assigned.append((item, bucket))
        return assigned

    @staticmethod
    def _balanced_indices(
        items: list[EvaluatedCandidate],
        candidates: list[int],
        capacity: int,
        spec: CompanySearchSpec,
    ) -> set[int]:
        if capacity <= 0 or not candidates:
            return set()
        if spec.balance_mode == BalanceMode.NONE or len(spec.verticals) == 1:
            return set(candidates[:capacity])

        by_vertical = {
            vertical.key: [
                index for index in candidates if items[index].target_vertical == vertical.key
            ]
            for vertical in spec.verticals
        }
        base, remainder = divmod(capacity, len(spec.verticals))
        picked: list[int] = []
        offsets: dict[str, int] = {}
        for lane_index, vertical in enumerate(spec.verticals):
            floor = base + (1 if lane_index < remainder else 0)
            lane_picks = by_vertical[vertical.key][:floor]
            picked.extend(lane_picks)
            offsets[vertical.key] = len(lane_picks)

        if spec.balance_mode == BalanceMode.STRICT:
            return set(picked)

        while len(picked) < capacity:
            added = False
            for vertical in spec.verticals:
                lane = by_vertical[vertical.key]
                offset = offsets[vertical.key]
                if offset < len(lane):
                    picked.append(lane[offset])
                    offsets[vertical.key] += 1
                    added = True
                    if len(picked) == capacity:
                        break
            if not added:
                break
        return set(picked)

    @staticmethod
    def _bucket_counts(
        items: list[EvaluatedCandidate],
        spec: CompanySearchSpec,
    ) -> dict[CandidateBucket, int]:
        return DiscoveryPipeline._count_assigned(
            DiscoveryPipeline._assign_buckets(items, spec, annotate=False)
        )

    @staticmethod
    def _count_assigned(
        assigned: list[tuple[EvaluatedCandidate, CandidateBucket]],
    ) -> dict[CandidateBucket, int]:
        counts = {bucket: 0 for bucket in CandidateBucket}
        for _, bucket in assigned:
            counts[bucket] += 1
        return counts

    def _results_per_search(self, spec: CompanySearchSpec) -> int:
        if "external_search" in spec.model_fields_set:
            return spec.external_search.results_per_search
        return self._results_per_query

    def _require_query_planner(self) -> QueryPlanner:
        if self._query_planner is None:
            raise RuntimeError("external discovery requires an LLM query planner (set LLM_API_KEY)")
        return self._query_planner

    def _require_evaluator(self) -> CandidateEvaluator:
        if self._evaluator is None:
            raise RuntimeError("candidate evaluation requires an LLM evaluator (set LLM_API_KEY)")
        return self._evaluator

    def _require_search_provider(self) -> CompanySearchProvider:
        if self._search_provider is None:
            raise RuntimeError("external discovery requires Exa (set EXA_API_KEY)")
        return self._search_provider

    def _query_count(self, spec: CompanySearchSpec) -> int:
        if self._query_planner is None:
            return spec.external_search.exa_searches
        return self._query_planner.query_count_for(spec)

    def _spec_summary(self, spec: CompanySearchSpec) -> str:
        states = ", ".join(spec.geography.states) or "all regions"
        size = (
            "any size"
            if spec.company_size.is_unbounded
            else f"{spec.company_size.employee_min or 1}-{spec.company_size.employee_max or 'unbounded'} employees"
        )
        verticals = ", ".join(vertical.label for vertical in spec.verticals)
        balancing = f"; balance {spec.balance_mode.value}" if len(spec.verticals) > 1 else ""
        search_budget = (
            f"; Exa {self._query_count(spec)} searches/lane x "
            f"{self._results_per_search(spec)} results"
        )
        return (
            f"{verticals}; {spec.geography.country} / {states}; {size}; "
            f"target {spec.count}{balancing}{search_budget}"
        )

    @staticmethod
    def _memory_filter_summary(spec: CompanySearchSpec) -> str:
        filters = [f"vertical={spec.vertical.key}", f"country={spec.geography.country}"]
        if spec.geography.states:
            filters.append(f"states={','.join(spec.geography.states)}")
        if not spec.company_size.is_unbounded:
            filters.append(
                f"employees={spec.company_size.employee_min or '*'}-{spec.company_size.employee_max or '*'}"
            )
        if spec.exclude.ownership_types:
            filters.append(f"ownership!={','.join(spec.exclude.ownership_types)}")
        filters.append(f"novelty={spec.novelty_mode.value}")
        return "; ".join(filters)
