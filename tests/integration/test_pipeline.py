from __future__ import annotations

from pathlib import Path
import json

from pydantic import BaseModel

from company_discovery.db.repository import DiscoveryRepository
from company_discovery.domain.models import (
    CandidateEvaluation,
    ExaSearchResult,
    ExclusionVerdict,
    FitVerdict,
    MatchVerdict,
    QueryPlan,
)
from company_discovery.domain.spec import CompanySearchSpec, NoveltyMode
from company_discovery.reports.exporter import ArtifactExporter
from company_discovery.services.evaluator import CandidateEvaluator
from company_discovery.services.pipeline import DiscoveryPipeline
from company_discovery.services.query_planner import QueryPlanner


class FakeLLM:
    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type[BaseModel]):
        if response_model is QueryPlan:
            return QueryPlan(
                queries=[f"Texas construction query {index}" for index in range(6)],
                rationale="Cover Texas construction terminology",
            )
        import json

        candidate = json.loads(user_prompt)["candidate"]
        possible = candidate["domain"] == "uncertain.com"
        return CandidateEvaluation(
            company_name=candidate["company_name"],
            domain=candidate["domain"],
            fit=FitVerdict.POSSIBLE if possible else FitVerdict.GOOD,
            vertical_match=MatchVerdict.YES,
            geography_match=MatchVerdict.YES,
            size_match=MatchVerdict.UNKNOWN if possible else MatchVerdict.LIKELY,
            excluded=ExclusionVerdict.NO,
            reason="Potential Texas construction company" if possible else "Texas construction company",
            reason_codes=["size_unknown"] if possible else [],
            evidence=["Official website snippet"],
            inferred_vertical="construction",
            inferred_country="US",
            inferred_state="TX",
            inferred_employee_min=None if possible else 20,
            inferred_employee_max=None if possible else 50,
            inferred_ownership_type=None,
        )

    def close(self) -> None:
        pass


class FakeExa:
    last_cost_dollars = 0.01

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, *, country: str, num_results: int) -> list[ExaSearchResult]:
        self.calls += 1
        urls = [
            ("Acme Builders | Texas", "https://acme.com"),
            ("Beta Construction", "https://beta.com/about"),
            ("Uncertain Co", "https://uncertain.com"),
            ("Acme on LinkedIn", "https://linkedin.com/company/acme"),
        ]
        return [
            ExaSearchResult(
                query=query,
                position=index,
                title=title,
                url=url,
                text="Texas commercial construction business",
                raw={"query": query, "url": url},
            )
            for index, (title, url) in enumerate(urls, start=1)
        ]

    def close(self) -> None:
        pass


def test_external_run_persists_exports_then_next_run_uses_memory_only(
    repository: DiscoveryRepository,
    spec: CompanySearchSpec,
    tmp_path: Path,
) -> None:
    llm = FakeLLM()
    exa = FakeExa()
    exporter = ArtifactExporter(tmp_path / "runs")
    first = DiscoveryPipeline(
        repository=repository,
        exporter=exporter,
        query_planner=QueryPlanner(llm, 6),
        evaluator=CandidateEvaluator(llm),
        search_provider=exa,
    ).discover(spec)

    assert exa.calls == 6
    assert first.summary.raw_results == 24
    assert first.summary.unique_candidates == 4
    assert first.summary.hygiene_rejected == 1
    assert first.summary.selected == 2
    assert first.summary.reserve == 1
    assert first.summary.rejected == 1
    for path in first.artifact_paths.values():
        assert Path(path).exists()
    exported_payload = json.loads(Path(first.artifact_paths["json"]).read_text())
    assert exported_payload["status"] == "completed"
    assert exported_payload["artifacts"]["json"] == first.artifact_paths["json"]
    assert "memory_trace" in exported_payload
    assert exported_payload["memory_trace"][0]["vertical"]["key"] == "construction"
    assert "reused" in exported_payload["memory_trace"][0]

    full_memory = spec.model_copy(update={"novelty_mode": NoveltyMode.FULL_MEMORY})
    second = DiscoveryPipeline(repository=repository, exporter=exporter).discover(full_memory)
    assert second.summary.memory_reused == 2
    assert second.summary.external_gap == 0
    assert second.summary.queries_generated == 0
    assert second.summary.selected == 2
    assert second.queries == []


def test_only_new_skips_memory_and_suppresses_all_known_external_domains(
    repository: DiscoveryRepository,
    spec: CompanySearchSpec,
    tmp_path: Path,
) -> None:
    llm = FakeLLM()
    exa = FakeExa()
    exporter = ArtifactExporter(tmp_path / "runs")
    pipeline = DiscoveryPipeline(
        repository=repository,
        exporter=exporter,
        query_planner=QueryPlanner(llm, 6),
        evaluator=CandidateEvaluator(llm),
        search_provider=exa,
    )
    pipeline.discover(spec)

    only_new = spec.model_copy(update={"novelty_mode": NoveltyMode.ONLY_NEW})
    result = pipeline.discover(only_new)

    assert result.summary.memory_matched == 0
    assert result.summary.memory_reused == 0
    assert result.summary.unique_candidates == 0
    assert result.summary.selected == 0
    payload = json.loads(Path(result.artifact_paths["json"]).read_text())
    trace = payload["memory_trace"][0]
    assert trace["mode"] == "bypassed"
    assert {item["domain"] for item in trace["external_domains_excluded"]} == {
        "acme.com",
        "beta.com",
        "uncertain.com",
        "linkedin.com",
    }


def test_default_policy_cannot_reselect_domains_returned_again_by_external_search(
    repository: DiscoveryRepository,
    spec: CompanySearchSpec,
    tmp_path: Path,
) -> None:
    llm = FakeLLM()
    exa = FakeExa()
    exporter = ArtifactExporter(tmp_path / "runs")
    pipeline = DiscoveryPipeline(
        repository=repository,
        exporter=exporter,
        query_planner=QueryPlanner(llm, 6),
        evaluator=CandidateEvaluator(llm),
        search_provider=exa,
    )
    pipeline.discover(spec)

    result = pipeline.discover(spec)

    previously_selected = {"acme.com", "beta.com"}
    assert all(
        candidate.candidate.domain not in previously_selected for candidate in result.candidates
    )
    payload = json.loads(Path(result.artifact_paths["json"]).read_text())
    excluded = payload["memory_trace"][0]["external_domains_excluded"]
    assert {item["domain"] for item in excluded} == {"acme.com", "beta.com"}
    assert {item["reason"] for item in excluded} == {"previously_selected"}


class MultiVerticalLLM:
    def __init__(self) -> None:
        self.planned_verticals: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str, response_model: type[BaseModel]):
        payload = json.loads(user_prompt)
        if response_model is QueryPlan:
            vertical = payload["search_spec"]["verticals"][0]["key"]
            self.planned_verticals.append(vertical)
            return QueryPlan(
                queries=[f"{vertical} query {index}" for index in range(6)],
                rationale=f"Dedicated {vertical} coverage",
            )

        candidate = payload["candidate"]
        is_good = not candidate["domain"].startswith("engineering")
        vertical = candidate["domain"].split("-")[0]
        return CandidateEvaluation(
            company_name=candidate["company_name"],
            domain=candidate["domain"],
            fit=FitVerdict.GOOD if is_good else FitVerdict.BAD,
            vertical_match=MatchVerdict.YES if is_good else MatchVerdict.NO,
            geography_match=MatchVerdict.YES,
            size_match=MatchVerdict.UNKNOWN,
            excluded=ExclusionVerdict.NO,
            reason="Fits lane" if is_good else "Does not fit lane",
            reason_codes=[] if is_good else ["vertical_mismatch"],
            evidence=[candidate["domain"]],
            inferred_vertical=vertical if is_good else None,
            inferred_country="US",
            inferred_state=None,
            inferred_employee_min=None,
            inferred_employee_max=None,
            inferred_ownership_type=None,
        )


class MultiVerticalExa:
    last_cost_dollars = 0.01

    def search(self, query: str, *, country: str, num_results: int) -> list[ExaSearchResult]:
        vertical = query.split()[0]
        totals = {"construction": 5, "healthcare": 1, "engineering": 1}
        return [
            ExaSearchResult(
                query=query,
                position=index,
                title=f"{vertical.title()} Company {index}",
                url=f"https://{vertical}-{index}.com",
                text=f"US {vertical} company",
                raw={"vertical": vertical},
            )
            for index in range(1, totals[vertical] + 1)
        ]


def test_multi_vertical_search_splits_lanes_and_soft_balance_reallocates_capacity(
    repository: DiscoveryRepository,
    tmp_path: Path,
) -> None:
    spec = CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 6,
            "verticals": [
                {"mode": "known", "key": "construction", "label": "Construction"},
                {"mode": "known", "key": "healthcare", "label": "Healthcare"},
                {"mode": "known", "key": "engineering", "label": "Engineering"},
            ],
            "reserve_ratio": 0,
            "balance_mode": "soft",
        }
    )
    llm = MultiVerticalLLM()
    result = DiscoveryPipeline(
        repository=repository,
        exporter=ArtifactExporter(tmp_path / "runs"),
        query_planner=QueryPlanner(llm, 6),
        evaluator=CandidateEvaluator(llm),
        search_provider=MultiVerticalExa(),
    ).discover(spec)

    assert llm.planned_verticals == ["construction", "healthcare", "engineering"]
    assert result.summary.queries_generated == 18
    selected = [candidate for candidate in result.candidates if candidate.bucket == "selected"]
    assert len(selected) == 6
    assert [candidate.target_vertical for candidate in selected].count("construction") == 5
    assert [candidate.target_vertical for candidate in selected].count("healthcare") == 1
    assert [candidate.target_vertical for candidate in selected].count("engineering") == 0
    assert all(candidate.evaluation.fit == FitVerdict.GOOD for candidate in selected)
