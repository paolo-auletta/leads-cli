from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from company_discovery.adapters.exa import ExaClient
from company_discovery.adapters.llm import OpenAICompatibleLLM
from company_discovery.adapters.website import WebsiteClient
from company_discovery.db.enrichment_repository import (
    EnrichmentRepository,
    EnrichmentRunNotFoundError,
)
from company_discovery.db.contact_repository import (
    ContactDiscoveryRepository,
    ContactNotFoundError,
    ContactRunNotFoundError,
)
from company_discovery.db.repository import CandidateNotFoundError, DiscoveryRepository, RunNotFoundError
from company_discovery.db.session import Database
from company_discovery.domain.models import EnrichmentSummary, RunSummary
from company_discovery.domain.contact_models import ContactDiscoverySummary
from company_discovery.domain.contact_spec import ContactSearchSpec
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.exporter import ArtifactExporter
from company_discovery.reports.enrichment_exporter import EnrichmentArtifactExporter
from company_discovery.reports.contact_exporter import ContactDiscoveryArtifactExporter
from company_discovery.services.contact_evaluator import ContactEvaluator
from company_discovery.services.contact_pipeline import ContactDiscoveryPipeline
from company_discovery.services.contact_progress import ContactProgressReporter
from company_discovery.services.enrichment_extractor import EnrichmentExtractor
from company_discovery.services.enrichment_pipeline import EnrichmentOptions, EnrichmentPipeline
from company_discovery.services.enrichment_progress import EnrichmentProgressReporter
from company_discovery.services.evaluator import CandidateEvaluator
from company_discovery.services.normalization import canonical_domain
from company_discovery.services.pipeline import DiscoveryPipeline
from company_discovery.services.progress import ProgressReporter
from company_discovery.services.query_planner import QueryPlanner
from company_discovery.settings import Settings, get_settings


app = typer.Typer(no_args_is_help=True, help="Company targeting and discovery.")
companies = typer.Typer(no_args_is_help=True, help="Discover and inspect target companies.")
contacts = typer.Typer(no_args_is_help=True, help="Discover current people at enriched companies.")
app.add_typer(companies, name="companies")
app.add_typer(contacts, name="contacts")
console = Console()


class RichProgressReporter(ProgressReporter):
    STYLES = {
        "spec": ("SPEC", "blue"),
        "memory": ("MEMORY", "green"),
        "external": ("EXA", "bright_cyan"),
        "evaluation": ("REVIEW", "yellow"),
        "save": ("OUTPUT", "bright_green"),
    }

    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self._style = "white"

    def stage(self, number: int, total: int, name: str, kind: str) -> None:
        label, self._style = self.STYLES[kind]
        title = Text(f"[{number}/{total}] {name}", style=f"bold {self._style}")
        console.print(Panel(Text(label, style=f"bold {self._style}"), title=title, expand=False))

    def info(self, message: str) -> None:
        console.print(f"  [{self._style}]*[/{self._style}] {message}")

    def detail(self, message: str) -> None:
        if self.verbose:
            console.print(f"    [dim]{message}[/dim]")

    def query(self, current: int, total: int, query: str, raw_total: int) -> None:
        suffix = f": {query}" if self.verbose else ""
        console.print(
            f"  [bright_cyan]SEARCH[/bright_cyan] query {current}/{total}; "
            f"{raw_total} raw results{suffix}"
        )

    def evaluation(
        self,
        current: int,
        total: int,
        selected: int,
        reserve: int,
        rejected: int,
        detail: str | None = None,
    ) -> None:
        suffix = f"; {detail}" if self.verbose and detail else ""
        console.print(
            f"  [yellow]REVIEW[/yellow] {current}/{total} | selected {selected} | "
            f"reserve {reserve} | rejected {rejected}{suffix}"
        )


class RichEnrichmentProgressReporter(EnrichmentProgressReporter):
    COLORS = {
        "INHERITED": "blue",
        "MEMORY": "green",
        "WEBSITE": "bright_cyan",
        "FALLBACK": "yellow",
        "READY": "bright_green",
        "REVIEW": "yellow",
        "BLOCKED": "red",
    }

    def start(self, discovery_run_id: str, total: int, bucket: str) -> None:
        console.print(
            Panel(
                f"Discovery run [bold]{discovery_run_id}[/bold]\n"
                f"{total} companies from [bold]{bucket}[/bold]",
                title="Company enrichment",
                border_style="bright_cyan",
            )
        )

    def company(self, current: int, total: int, name: str) -> None:
        console.print(f"\n[bold bright_cyan][{current}/{total}] {name}[/bold bright_cyan]")

    def event(self, label: str, message: str) -> None:
        color = self.COLORS.get(label, "white")
        console.print(f"  [{color}]{label:<9}[/{color}] {message}")


class RichContactProgressReporter(ContactProgressReporter):
    def start(self, source_run_id: str, companies_count: int, roles: int) -> None:
        console.print(
            Panel(
                f"Company enrichment run [bold]{source_run_id}[/bold]\n"
                f"{companies_count} companies | {roles} role targets",
                title="Contact discovery",
                border_style="bright_cyan",
            )
        )

    def company(self, current: int, total: int, name: str, domain: str) -> None:
        console.print(
            f"\n[bold bright_cyan][{current}/{total}] {name}[/bold bright_cyan] "
            f"[dim]{domain}[/dim]"
        )

    def memory(self, role: str, reused: int, target: int) -> None:
        console.print(
            f"  [green]MEMORY[/green] {role}: reused {reused}/{target}; "
            f"live gap {max(0, target - reused)}"
        )

    def search(self, role: str, current: int, total: int, results: int) -> None:
        console.print(
            f"  [bright_cyan]LIVE WEB[/bright_cyan] {role}: query {current}/{total}; "
            f"{results} unique results"
        )

    def evaluation(self, role: str, accepted: int, review: int, rejected: int) -> None:
        console.print(
            f"  [yellow]VERIFY[/yellow] {role}: accepted {accepted} | "
            f"review {review} | rejected {rejected}"
        )

    def save(self, run_id: str) -> None:
        console.print(f"\n  [bright_green]OUTPUT[/bright_green] saved {run_id}")

def build_runtime(settings: Settings) -> tuple[Database, DiscoveryRepository, DiscoveryPipeline, list[object]]:
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = DiscoveryRepository(database)
    resources: list[object] = []

    llm = None
    if settings.llm_api_key:
        llm = OpenAICompatibleLLM(settings)
        resources.append(llm)
    exa = None
    if settings.exa_api_key:
        exa = ExaClient(settings)
        resources.append(exa)

    pipeline = DiscoveryPipeline(
        repository=repository,
        exporter=ArtifactExporter(settings.artifacts_dir),
        query_planner=QueryPlanner(llm, settings.query_count) if llm else None,
        evaluator=CandidateEvaluator(llm) if llm else None,
        search_provider=exa,
        results_per_query=settings.exa_results_per_query,
    )
    return database, repository, pipeline, resources


def build_enrichment_runtime(
    settings: Settings,
) -> tuple[Database, EnrichmentRepository, EnrichmentPipeline, list[object]]:
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = EnrichmentRepository(database)
    resources: list[object] = []

    llm = OpenAICompatibleLLM(settings) if settings.llm_api_key else None
    if llm:
        resources.append(llm)
    exa = ExaClient(settings) if settings.exa_api_key else None
    if exa:
        resources.append(exa)
    website = WebsiteClient(
        timeout_seconds=settings.enrichment_website_timeout_seconds,
        max_pages=settings.enrichment_max_pages,
    )
    resources.append(website)
    pipeline = EnrichmentPipeline(
        repository=repository,
        exporter=EnrichmentArtifactExporter(settings.artifacts_dir),
        website=website,
        extractor=EnrichmentExtractor(llm) if llm else None,
        fallback_search=exa,
        freshness_days=settings.enrichment_freshness_days,
        fallback_results=settings.enrichment_fallback_results,
    )
    return database, repository, pipeline, resources


def build_contact_runtime(
    settings: Settings,
) -> tuple[Database, ContactDiscoveryRepository, ContactDiscoveryPipeline, list[object]]:
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = ContactDiscoveryRepository(database)
    resources: list[object] = []

    llm = OpenAICompatibleLLM(settings) if settings.llm_api_key else None
    if llm:
        resources.append(llm)
    exa = ExaClient(settings) if settings.exa_api_key else None
    if exa:
        resources.append(exa)
    pipeline = ContactDiscoveryPipeline(
        repository=repository,
        exporter=ContactDiscoveryArtifactExporter(settings.artifacts_dir),
        search_provider=exa,
        evaluator=ContactEvaluator(llm) if llm else None,
        results_per_query=settings.contact_results_per_query,
    )
    return database, repository, pipeline, resources


def close_runtime(database: Database, resources: list[object]) -> None:
    for resource in resources:
        close = getattr(resource, "close", None)
        if close:
            close()
    database.dispose()


def _next_runs_archive_path(home: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = home / f"runs-previousdb-{timestamp}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = home / f"{base.name}-{suffix}"
        suffix += 1
    return candidate


@app.command("init-db")
def init_db() -> None:
    """Create the database schema, optionally resetting an existing database."""
    settings = get_settings()
    database_path = settings.sqlite_database_path
    if database_path is None:
        console.print(
            "[bold red]Cannot initialize database:[/bold red] "
            "init-db requires an on-disk SQLite DATABASE_URL."
        )
        raise typer.Exit(2)

    resetting = database_path.exists()
    if resetting and not typer.confirm(
        f"{database_path} already exists. Reset it and archive the current runs?",
        default=False,
    ):
        console.print("Database reset cancelled; nothing was changed.")
        return

    archived_runs: Path | None = None
    if resetting and settings.artifacts_dir.exists():
        archived_runs = _next_runs_archive_path(settings.company_discovery_home)
        settings.artifacts_dir.rename(archived_runs)

    if resetting:
        database_path.unlink()
        for suffix in ("-wal", "-shm"):
            database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)

    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    try:
        database.create_schema()
    finally:
        database.dispose()

    message = f"Created a fresh database at [bold]{database_path}[/bold]."
    if archived_runs is not None:
        message += f"\nArchived previous run artifacts to [bold]{archived_runs}[/bold]."
    console.print(Panel(message, title="Database initialized", border_style="bright_green"))


@companies.command("discover")
def discover(
    spec_path: Annotated[Path, typer.Option("--spec", exists=True, dir_okay=False, readable=True)],
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Discover companies from a validated JSON search spec."""
    try:
        spec = CompanySearchSpec.from_file(spec_path)
    except (ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid search spec:[/bold red] {exc}")
        raise typer.Exit(2) from exc

    settings = get_settings()
    database, _, pipeline, resources = build_runtime(settings)
    try:
        result = pipeline.discover(
            spec,
            source_spec_path=spec_path,
            progress=RichProgressReporter(verbose=verbose),
        )
    except Exception as exc:
        console.print(f"[bold red]Discovery failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)

    console.print(
        Panel(
            f"Run [bold]{result.run_id}[/bold]\n"
            f"Selected {result.summary.selected} | Reserve {result.summary.reserve} | "
            f"Rejected {result.summary.rejected}\n"
            f"Summary: {result.artifact_paths['summary']}",
            title="Discovery complete",
            border_style="bright_green",
        )
    )
@companies.command("enrich")
def enrich(
    discovery_run_id: str,
    bucket: Annotated[str, typer.Option("--bucket")] = "selected",
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    refresh: Annotated[
        str,
        typer.Option(help="Refresh scope: none, contact, independence, or all."),
    ] = "none",
    allow_unknown_independence: Annotated[
        bool,
        typer.Option(
            "--allow-unknown-independence",
            help="Allow complete profiles with unknown independence into enriched.csv.",
        ),
    ] = False,
) -> None:
    """Enrich companies selected by a completed discovery run."""
    if bucket not in {"selected", "reserve"}:
        console.print("[bold red]Invalid bucket:[/bold red] use selected or reserve")
        raise typer.Exit(2)
    if refresh not in {"none", "contact", "independence", "all"}:
        console.print(
            "[bold red]Invalid refresh scope:[/bold red] use none, contact, independence, or all"
        )
        raise typer.Exit(2)
    _execute_enrichment(
        discovery_run_id,
        EnrichmentOptions(
            bucket=bucket,
            limit=limit,
            refresh=refresh,
            allow_unknown_independence=allow_unknown_independence,
        ),
    )


def _execute_enrichment(discovery_run_id: str, options: EnrichmentOptions) -> None:
    settings = get_settings()
    database, _, pipeline, resources = build_enrichment_runtime(settings)
    try:
        result = pipeline.enrich(
            discovery_run_id,
            options=options,
            progress=RichEnrichmentProgressReporter(),
        )
    except Exception as exc:
        console.print(f"[bold red]Enrichment failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)
    console.print(
        Panel(
            f"Run [bold]{result.run_id}[/bold]\n"
            f"Ready {result.summary.ready} | Review {result.summary.review} | "
            f"Blocked {result.summary.blocked} | Failed {result.summary.failed}\n"
            f"Output: {result.artifact_paths['enriched']}",
            title="Enrichment complete",
            border_style="bright_green",
        )
    )


@companies.command("show-enrichment")
def show_enrichment(run_id: str) -> None:
    """Show counts, source run, and artifacts for an enrichment run."""
    database, repository, _, resources = build_enrichment_runtime(get_settings())
    try:
        payload = repository.get_run(run_id)
        summary = payload["summary"]
        console.print(
            Panel(
                f"Status: {payload['status']}\n"
                f"Discovery run: {payload['discovery_run_id']}\n"
                f"Input bucket: {payload['bucket']}\n"
                f"Processed: {summary.get('processed', 0)} | Ready: {summary.get('ready', 0)} | "
                f"Review: {summary.get('review', 0)} | Blocked: {summary.get('blocked', 0)}",
                title=f"Enrichment {run_id}",
            )
        )
        if payload["artifacts"]:
            console.print_json(json.dumps(payload["artifacts"], ensure_ascii=True))
    except EnrichmentRunNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("inspect-enrichment")
def inspect_enrichment(run_id: str, domain: Annotated[str, typer.Option("--domain")]) -> None:
    """Inspect one enriched company including provenance, conflicts, and trace."""
    normalized = canonical_domain(domain)
    if normalized is None:
        console.print(f"[bold red]Invalid domain:[/bold red] {domain}")
        raise typer.Exit(2)
    database, repository, _, resources = build_enrichment_runtime(get_settings())
    try:
        console.print_json(json.dumps(repository.inspect_item(run_id, normalized), ensure_ascii=True))
    except (EnrichmentRunNotFoundError, CandidateNotFoundError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("export-enrichment")
def export_enrichment(run_id: str) -> None:
    """Regenerate enrichment CSV, Markdown, and JSON artifacts."""
    settings = get_settings()
    database, repository, _, resources = build_enrichment_runtime(settings)
    try:
        payload = repository.get_run(run_id)
        if payload["status"] != "completed":
            raise ValueError(f"enrichment run {run_id} is {payload['status']}, not completed")
        summary = EnrichmentSummary.model_validate(payload["summary"])
        paths = EnrichmentArtifactExporter(settings.artifacts_dir).export(payload, summary)
        repository.set_artifacts(run_id, paths)
        console.print(f"Exported enrichment [bold]{run_id}[/bold] to {Path(paths['json']).parent}")
    except (EnrichmentRunNotFoundError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("validate-spec")
def validate_spec(
    spec_path: Annotated[Path, typer.Option("--spec", exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate and print the normalized form of a search spec without running discovery."""
    try:
        spec = CompanySearchSpec.from_file(spec_path)
    except (ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid search spec:[/bold red] {exc}")
        raise typer.Exit(2) from exc
    console.print("[bold green]Valid company search spec[/bold green]")
    console.print_json(spec.model_dump_json(indent=2))
    for condition in spec.missing_constraints:
        console.print(f"[yellow]Note:[/yellow] {condition}")


@companies.command("show-run")
def show_run(run_id: str) -> None:
    """Show the spec, queries, counts, and artifacts for a prior run."""
    database, repository, _, resources = build_runtime(get_settings())
    try:
        payload = repository.get_run(run_id)
        _render_run(payload)
    except RunNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("export")
def export_run(run_id: str) -> None:
    """Regenerate CSV, Markdown, and JSON artifacts for a prior run."""
    settings = get_settings()
    database, repository, _, resources = build_runtime(settings)
    try:
        payload = repository.get_run(run_id)
        if payload["status"] != "completed":
            raise ValueError(f"run {run_id} is {payload['status']}, not completed")
        summary = RunSummary.model_validate(payload["summary"])
        paths = ArtifactExporter(settings.artifacts_dir).export(payload, summary)
        repository.set_artifacts(run_id, paths)
        console.print(f"Exported run [bold]{run_id}[/bold] to {Path(paths['summary']).parent}")
    except (RunNotFoundError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("inspect")
def inspect(run_id: str, domain: Annotated[str, typer.Option("--domain")]) -> None:
    """Inspect one run candidate, its evidence, and its evaluation."""
    normalized = canonical_domain(domain)
    if normalized is None:
        console.print(f"[bold red]Invalid domain:[/bold red] {domain}")
        raise typer.Exit(2)
    database, repository, _, resources = build_runtime(get_settings())
    try:
        payload = repository.inspect_candidate(run_id, normalized)
        console.print_json(json.dumps(payload, ensure_ascii=True))
    except CandidateNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@companies.command("rerun")
def rerun(
    run_id: str,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run a prior immutable spec again with its saved novelty policy."""
    settings = get_settings()
    database, repository, pipeline, resources = build_runtime(settings)
    try:
        prior = repository.get_run(run_id)
        spec = CompanySearchSpec.model_validate(prior["spec"])
        result = pipeline.discover(spec, progress=RichProgressReporter(verbose=verbose))
        console.print(
            f"Rerun complete: [bold]{result.run_id}[/bold] | selected {result.summary.selected} | "
            f"reserve {result.summary.reserve} | rejected {result.summary.rejected}"
        )
    except RunNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(f"[bold red]Rerun failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


def _render_run(payload: dict[str, object]) -> None:
    spec = payload["spec"]
    assert isinstance(spec, dict)
    summary = payload["summary"]
    assert isinstance(summary, dict)
    verticals = spec["verticals"]
    geography = spec["geography"]
    assert isinstance(verticals, list) and isinstance(geography, dict)
    vertical_labels = ", ".join(
        str(vertical["label"]) for vertical in verticals if isinstance(vertical, dict)
    )
    console.print(
        Panel(
            f"Status: {payload['status']}\n"
            f"Verticals: {vertical_labels}\n"
            f"Balance: {spec.get('balance_mode', 'soft')}\n"
            f"Novelty: {spec.get('novelty_mode', 'unused_memory')}\n"
            f"Geography: {geography['country']} / {', '.join(geography['states']) or 'all'}\n"
            f"Requested: {spec['count']}",
            title=f"Run {payload['run_id']}",
        )
    )
    table = Table("Metric", "Count")
    for key in ("memory_matched", "memory_reused", "external_gap", "raw_results", "selected", "reserve", "rejected"):
        table.add_row(key.replace("_", " ").title(), str(summary.get(key, 0)))
    console.print(table)
    queries = payload["queries"]
    assert isinstance(queries, list)
    if queries:
        console.print("[bold]Queries[/bold]")
        for query in queries:
            console.print(f"  * {query}")
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    if artifacts:
        console.print("[bold]Artifacts[/bold]")
        for name, path in artifacts.items():
            console.print(f"  {name}: {path}")


@contacts.command("validate-spec")
def validate_contact_spec(
    spec_path: Annotated[Path, typer.Option("--spec", exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate and print a normalized contact discovery spec."""
    try:
        spec = ContactSearchSpec.from_file(spec_path)
    except (ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid contact spec:[/bold red] {exc}")
        raise typer.Exit(2) from exc
    console.print("[bold green]Valid contact search spec[/bold green]")
    console.print_json(spec.model_dump_json(indent=2))


@contacts.command("discover")
def discover_contacts(
    spec_path: Annotated[Path, typer.Option("--spec", exists=True, dir_okay=False, readable=True)],
) -> None:
    """Discover current role-matched people at enriched companies."""
    try:
        spec = ContactSearchSpec.from_file(spec_path)
    except (ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid contact spec:[/bold red] {exc}")
        raise typer.Exit(2) from exc

    database, _, pipeline, resources = build_contact_runtime(get_settings())
    try:
        result = pipeline.discover(
            spec,
            source_spec_path=spec_path,
            progress=RichContactProgressReporter(),
        )
    except Exception as exc:
        console.print(f"[bold red]Contact discovery failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)

    console.print(
        Panel(
            f"Run [bold]{result.run_id}[/bold]\n"
            f"Accepted {result.summary.accepted} | Review {result.summary.review} | "
            f"Rejected {result.summary.rejected}\n"
            f"Output: {result.artifact_paths['accepted']}",
            title="Contact discovery complete",
            border_style="bright_green",
        )
    )


@contacts.command("show-run")
def show_contact_run(run_id: str) -> None:
    """Show scope, counts, queries, and artifacts for a contact discovery run."""
    database, repository, _, resources = build_contact_runtime(get_settings())
    try:
        payload = repository.get_run(run_id)
        summary = payload["summary"]
        console.print(
            Panel(
                f"Status: {payload['status']}\n"
                f"Company enrichment run: {payload['source_enrichment_run_id']}\n"
                f"Companies: {summary.get('companies_loaded', 0)} | "
                f"Memory: {summary.get('memory_reused', 0)} | "
                f"Queries: {summary.get('queries_run', 0)}\n"
                f"Accepted: {summary.get('accepted', 0)} | "
                f"Review: {summary.get('review', 0)} | "
                f"Rejected: {summary.get('rejected', 0)}",
                title=f"Contact run {run_id}",
            )
        )
        if payload["artifacts"]:
            console.print_json(json.dumps(payload["artifacts"], ensure_ascii=True))
    except ContactRunNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@contacts.command("inspect")
def inspect_contact(
    run_id: str,
    person: Annotated[str, typer.Option("--person")],
) -> None:
    """Inspect one person's role decisions and live evidence."""
    database, repository, _, resources = build_contact_runtime(get_settings())
    try:
        console.print_json(
            json.dumps(repository.inspect_contact(run_id, person), ensure_ascii=True)
        )
    except (ContactRunNotFoundError, ContactNotFoundError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


@contacts.command("export")
def export_contact_run(run_id: str) -> None:
    """Regenerate contact discovery artifacts from the stored run."""
    settings = get_settings()
    database, repository, _, resources = build_contact_runtime(settings)
    try:
        payload = repository.get_run(run_id)
        if payload["status"] != "completed":
            raise ValueError(f"contact run {run_id} is {payload['status']}, not completed")
        summary = ContactDiscoverySummary.model_validate(payload["summary"])
        paths = ContactDiscoveryArtifactExporter(settings.artifacts_dir).export(payload, summary)
        repository.set_artifacts(run_id, paths)
        console.print(f"Exported contact run [bold]{run_id}[/bold] to {Path(paths['json']).parent}")
    except (ContactRunNotFoundError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        close_runtime(database, resources)


if __name__ == "__main__":
    app()
