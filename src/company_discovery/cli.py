from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from importlib import metadata
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import questionary
import httpx
import typer
from pydantic import ValidationError
from questionary import Choice, Style
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from company_discovery.adapters.exa import ExaClient
from company_discovery.adapters.apollo import ApolloClient
from company_discovery.adapters.llm import build_llm
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
from company_discovery.db.contact_enrichment_repository import (
    ContactEnrichmentRepository,
    ContactEnrichmentRunNotFoundError,
)
from company_discovery.db.repository import CandidateNotFoundError, DiscoveryRepository, RunNotFoundError
from company_discovery.db.session import Database
from company_discovery.domain.models import EnrichmentSummary, RunSummary
from company_discovery.domain.contact_models import (
    ContactDiscoverySummary,
    ContactEnrichmentSummary,
)
from company_discovery.domain.contact_spec import ContactSearchSpec
from company_discovery.domain.spec import CompanySearchSpec
from company_discovery.reports.exporter import ArtifactExporter
from company_discovery.reports.enrichment_exporter import EnrichmentArtifactExporter
from company_discovery.reports.contact_exporter import ContactDiscoveryArtifactExporter
from company_discovery.reports.contact_enrichment_exporter import (
    ContactEnrichmentArtifactExporter,
)
from company_discovery.services.contact_evaluator import ContactEvaluator
from company_discovery.services.contact_pipeline import ContactDiscoveryPipeline
from company_discovery.services.contact_progress import ContactProgressReporter
from company_discovery.services.contact_enrichment_pipeline import (
    ContactEnrichmentOptions,
    ContactEnrichmentPipeline,
)
from company_discovery.services.contact_enrichment_progress import (
    ContactEnrichmentProgressReporter,
)
from company_discovery.services.enrichment_extractor import EnrichmentExtractor
from company_discovery.services.enrichment_pipeline import EnrichmentOptions, EnrichmentPipeline
from company_discovery.services.enrichment_progress import EnrichmentProgressReporter
from company_discovery.services.evaluator import CandidateEvaluator
from company_discovery.services.normalization import canonical_domain
from company_discovery.services.pipeline import DiscoveryPipeline
from company_discovery.services.progress import ProgressReporter
from company_discovery.services.query_planner import QueryPlanner
from company_discovery.settings import Settings, get_settings
from company_discovery import __distribution_name__, __version__
from company_discovery.migrations import (
    MigrationError,
    WorkspaceSchemaBlockedError,
    apply_migrations,
    ensure_workspace_schema_current,
    migration_status,
)
from company_discovery.runtime import (
    SCHEMA_VERSION,
    SKILL_BUNDLE_VERSION,
    configure_workspace_logging,
    default_workspace_root,
    ensure_workspace,
    merge_dicts,
    read_toml,
    update_config_value,
    write_workspace_pointer,
)
from company_discovery.skill_installer import (
    detect_targets,
    install_skills,
    installed_target_keys,
    skill_status,
)
from company_discovery.update_plan import build_update_check


app = typer.Typer(no_args_is_help=True, help="Company targeting and discovery.")
companies = typer.Typer(no_args_is_help=True, help="Discover and inspect target companies.")
contacts = typer.Typer(
    no_args_is_help=True,
    help="Discover current people and enrich their contact channels.",
)
config_app = typer.Typer(no_args_is_help=True, help="Inspect and update local configuration.")
skills_app = typer.Typer(no_args_is_help=True, help="Install and inspect bundled agent skills.")
app.add_typer(companies, name="companies")
app.add_typer(contacts, name="contacts")
app.add_typer(config_app, name="config")
app.add_typer(skills_app, name="skills")
console = Console()
WEBHOOK_SITE_BASE_URL = "https://webhook.site"

ONBOARDING_STYLE = Style(
    [
        ("qmark", "fg:#6ec6b8 bold"),
        ("question", "bold"),
        ("answer", "fg:#ffb000 bold"),
        ("pointer", "fg:#ffffff bold"),
        ("highlighted", "noreverse fg:#ffffff bold"),
        ("selected", "noreverse fg:#ffffff"),
        ("disabled", "fg:#8a9099"),
        ("instruction", "fg:#c8cdd4"),
        ("validation-toolbar", "noreverse fg:#ff6b6b bold"),
    ]
)


MODEL_PICKER_LIMIT = 12
LITELLM_PROVIDER_MODEL_LISTS = {
    "openai": ("open_ai_chat_completion_models", "openai"),
    "deepseek": ("deepseek_models", "deepseek"),
    "anthropic": ("anthropic_models", "anthropic"),
    "google-gemini": ("gemini_models", "gemini"),
}
PREFERRED_PROVIDER_MODELS = {
    "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
    "google-gemini": [
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash",
    ],
}
NON_CHAT_MODEL_MARKERS = (
    "audio",
    "dall-e",
    "embedding",
    "image",
    "imagen",
    "moderation",
    "realtime",
    "robotics",
    "sora",
    "transcribe",
    "tts",
    "veo",
    "whisper",
)
NON_CHAT_MODEL_NAMES = {"container"}


@lru_cache(maxsize=None)
def _litellm_provider_models(provider: str) -> tuple[str, ...]:
    normalized_provider = provider.strip().lower()
    model_source = LITELLM_PROVIDER_MODEL_LISTS.get(normalized_provider)
    if not model_source:
        return ()
    attr_name, provider_prefix = model_source
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    try:
        import litellm
    except Exception:
        return ()

    raw_models = getattr(litellm, attr_name, ())
    models = []
    seen = set()
    for raw_model in sorted(str(model) for model in raw_models):
        model = _strip_provider_model_prefix(raw_model, provider_prefix)
        if not _looks_like_chat_model(model):
            continue
        if model not in seen:
            seen.add(model)
            models.append(model)
    preferred = [
        model
        for model in PREFERRED_PROVIDER_MODELS.get(normalized_provider, [])
        if model in seen
    ]
    remaining = [model for model in models if model not in set(preferred)]
    return tuple([*preferred, *remaining])


def _litellm_picker_models(provider: str) -> list[str]:
    return list(_litellm_provider_models(provider)[:MODEL_PICKER_LIMIT])


def _strip_provider_model_prefix(model: str, provider_prefix: str) -> str:
    prefix = f"{provider_prefix}/"
    if model.startswith(prefix):
        return model.removeprefix(prefix)
    return model


def _looks_like_chat_model(model: str) -> bool:
    lower_model = model.lower()
    if lower_model in NON_CHAT_MODEL_NAMES:
        return False
    return not any(marker in lower_model for marker in NON_CHAT_MODEL_MARKERS)


def _known_provider_model_error(provider: str, model: str) -> str | None:
    provider_choice = _provider_choice(provider)
    if not provider_choice or provider_choice["key"] == "custom":
        return None
    provider_key = str(provider_choice["key"])
    known_models = set(_litellm_provider_models(provider_key))
    if not known_models:
        return None
    _, provider_prefix = LITELLM_PROVIDER_MODEL_LISTS[provider_key]
    normalized_model = _strip_provider_model_prefix(model.strip(), provider_prefix)
    if normalized_model in known_models:
        return None
    examples = ", ".join(list(_litellm_provider_models(provider_key))[:3])
    return (
        f"'{model}' is not in LiteLLM's known {provider_choice['label']} model registry. "
        f"Try one of: {examples}, or choose Custom OpenAI-compatible endpoint for external routers."
    )


LLM_PROVIDER_CHOICES = [
    {
        "key": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "supported": True,
        "models": _litellm_picker_models("openai"),
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "supported": True,
        "models": _litellm_picker_models("deepseek"),
    },
    {
        "key": "anthropic",
        "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "supported": True,
        "models": _litellm_picker_models("anthropic"),
    },
    {
        "key": "google-gemini",
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "supported": True,
        "models": _litellm_picker_models("google-gemini"),
    },
    {
        "key": "custom",
        "label": "Custom OpenAI-compatible endpoint",
        "base_url": "https://api.openai.com/v1",
        "supported": True,
        "models": [],
    },
]
CUSTOM_MODEL_VALUE = "__custom_model__"


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


class RichContactEnrichmentProgressReporter(ContactEnrichmentProgressReporter):
    def start(self, source_run_id: str, contacts_count: int) -> None:
        console.print(
            Panel(
                f"Contact discovery run [bold]{source_run_id}[/bold]\n"
                f"{contacts_count} accepted contacts",
                title="Apollo contact enrichment",
                border_style="bright_cyan",
            )
        )

    def memory(self, reused: int, pending: int) -> None:
        console.print(
            f"  [green]MEMORY[/green] reused {reused} fresh profiles | "
            f"Apollo gap {pending}"
        )

    def batch(self, current: int, total: int, size: int) -> None:
        console.print(
            f"  [bright_cyan]APOLLO[/bright_cyan] batch {current}/{total} | {size} people"
        )

    def poll(self, request_id: str, attempt: int) -> None:
        console.print(
            f"  [yellow]POLL[/yellow] {request_id} | attempt {attempt}"
        )

    def outcome(self, name: str, outcome: str, flags: list[str]) -> None:
        color = {"ready": "bright_green", "review": "yellow", "blocked": "red"}[outcome]
        suffix = f" | {', '.join(flags)}" if flags else ""
        console.print(f"  [{color}]{outcome.upper():<7}[/{color}] {name}{suffix}")

    def save(self, run_id: str) -> None:
        console.print(f"\n  [bright_green]OUTPUT[/bright_green] saved {run_id}")

def build_runtime(settings: Settings) -> tuple[Database, DiscoveryRepository, DiscoveryPipeline, list[object]]:
    _ensure_schema_ready(settings)
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = DiscoveryRepository(database)
    resources: list[object] = []

    llm = None
    if settings.llm_api_key:
        llm = build_llm(settings)
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
    _ensure_schema_ready(settings)
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = EnrichmentRepository(database)
    resources: list[object] = []

    llm = build_llm(settings) if settings.llm_api_key else None
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
    _ensure_schema_ready(settings)
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = ContactDiscoveryRepository(database)
    resources: list[object] = []

    llm = build_llm(settings) if settings.llm_api_key else None
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


def build_contact_enrichment_runtime(
    settings: Settings,
) -> tuple[
    Database,
    ContactEnrichmentRepository,
    ContactEnrichmentPipeline,
    list[object],
]:
    _ensure_schema_ready(settings)
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    repository = ContactEnrichmentRepository(database)
    provider = ApolloClient(settings)
    pipeline = ContactEnrichmentPipeline(
        repository=repository,
        exporter=ContactEnrichmentArtifactExporter(settings.artifacts_dir),
        provider=provider,
        freshness_days=settings.apollo_enrichment_freshness_days,
        poll_interval_seconds=settings.apollo_poll_interval_seconds,
        poll_timeout_seconds=settings.apollo_poll_timeout_seconds,
    )
    return database, repository, pipeline, [provider]


def build_contact_enrichment_repository(
    settings: Settings,
) -> tuple[Database, ContactEnrichmentRepository]:
    _ensure_schema_ready(settings)
    settings.prepare_directories()
    database = Database(settings.resolved_database_url)
    database.create_schema()
    return database, ContactEnrichmentRepository(database)


def close_runtime(database: Database, resources: list[object]) -> None:
    for resource in resources:
        close = getattr(resource, "close", None)
        if close:
            close()
    database.dispose()


def _ensure_schema_ready(settings: Settings) -> None:
    try:
        ensure_workspace_schema_current(settings)
    except WorkspaceSchemaBlockedError as exc:
        console.print(Panel(str(exc), title="Workspace migration required", border_style="red"))
        raise typer.Exit(2) from exc


def _next_runs_archive_path(home: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = home / f"runs-previousdb-{timestamp}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = home / f"{base.name}-{suffix}"
        suffix += 1
    return candidate


def _installed_cli_version() -> str:
    try:
        return metadata.version(__distribution_name__)
    except metadata.PackageNotFoundError:
        return __version__


def _mask_secrets(data: dict[str, object]) -> dict[str, object]:
    masked = json.loads(json.dumps(data))
    sensitive_keys = {"api_key", "webhook_url"}

    def mask(value: object) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key in sensitive_keys and child:
                value[key] = "********"
            elif key == "apollo" and child and not isinstance(child, dict):
                value[key] = "********"
            else:
                mask(child)

    mask(masked)
    return masked


def _nested_value(data: dict[str, object], dotted_key: str, default: object = None) -> object:
    cursor: object = data
    for key in dotted_key.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


def _create_webhook_site_url(
    base_url: str = WEBHOOK_SITE_BASE_URL,
    *,
    client: httpx.Client | None = None,
) -> tuple[str | None, str]:
    normalized_base = base_url.rstrip("/")
    owns_client = client is None
    http_client = client or httpx.Client(base_url=normalized_base, timeout=30)
    try:
        response = http_client.post("/token")
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http_client.close()
    if not isinstance(payload, dict):
        raise RuntimeError("Webhook.site returned an unexpected token response")
    token_id = payload.get("uuid") or payload.get("id") or payload.get("token")
    url = payload.get("url") or payload.get("webhook_url")
    if not url and token_id:
        url = f"{normalized_base}/{token_id}"
    if not url:
        raise RuntimeError("Webhook.site token response did not include a usable URL")
    return str(token_id) if token_id else None, str(url)


def _provider_base_url(provider: str, current: str | None = None) -> str:
    provider_choice = _provider_choice(provider)
    if provider_choice and provider_choice["supported"] and provider_choice["key"] != "custom":
        return str(provider_choice["base_url"])
    return current or "https://api.openai.com/v1"


def _provider_choice(provider: str) -> dict[str, object] | None:
    normalized = provider.strip().lower()
    return next(
        (
            choice
            for choice in LLM_PROVIDER_CHOICES
            if choice["key"] == normalized or str(choice["label"]).lower() == normalized
        ),
        None,
    )


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and not os.getenv("LEADS_TEXT_PROMPTS")


def _desktop_workspace_root() -> Path:
    return Path.home() / "Desktop" / "Leads"


def _workspace_choices(recommended: Path) -> list[dict[str, object]]:
    desktop = _desktop_workspace_root()
    return [
        {
            "key": "recommended",
            "label": f"Recommended path ({recommended})",
            "path": recommended,
        },
        {
            "key": "desktop",
            "label": f"Desktop ({desktop})",
            "path": desktop,
        },
        {
            "key": "custom",
            "label": "Custom path",
            "path": None,
        },
    ]


def _select_workspace_root(recommended: Path) -> Path:
    choices = _workspace_choices(recommended)
    selected = _select_choice("Workspace location", choices, default="recommended")
    if selected == "custom":
        return Path(_prompt_required("Custom workspace path")).expanduser()
    choice = next(choice for choice in choices if choice["key"] == selected)
    return Path(choice["path"]).expanduser()


def _select_choice(
    message: str,
    choices: list[dict[str, object]],
    *,
    default: str | None = None,
) -> str:
    if _interactive_terminal():
        questionary_choices = [
            Choice(
                title=str(choice["label"]),
                value=str(choice["key"]),
                disabled=str(choice["disabled"]) if choice.get("disabled") else None,
            )
            for choice in choices
        ]
        answer = questionary.select(
            message,
            choices=questionary_choices,
            default=default,
            use_indicator=False,
            use_shortcuts=False,
            instruction="Use up/down and enter.",
            style=ONBOARDING_STYLE,
        ).ask()
        if answer is None:
            raise typer.Exit(130)
        return str(answer)

    enabled = [choice for choice in choices if not choice.get("disabled")]
    options = ", ".join(str(choice["label"]) for choice in enabled)
    while True:
        answer = typer.prompt(f"{message} ({options})", default=default or str(enabled[0]["key"]))
        selected = next(
            (
                choice
                for choice in choices
                if str(choice["key"]).lower() == answer.strip().lower()
                or str(choice["label"]).lower() == answer.strip().lower()
            ),
            None,
        )
        if selected and not selected.get("disabled"):
            return str(selected["key"])
        if selected and selected.get("disabled"):
            console.print(f"[yellow]{selected['label']} is not available yet: {selected['disabled']}[/yellow]")
        else:
            console.print(f"[yellow]Choose one of: {options}[/yellow]")


def _select_model(provider: str, current_model: str) -> str:
    provider_choice = _provider_choice(provider)
    models = list((provider_choice or {}).get("models", []))
    example = models[0] if models else current_model or "my-model-name"
    model_choices = [{"key": model, "label": model} for model in models]
    model_choices.append(
        {
            "key": CUSTOM_MODEL_VALUE,
            "label": f"Write my own model (e.g. {example})",
        }
    )
    default = current_model if any(choice["key"] == current_model for choice in model_choices) else CUSTOM_MODEL_VALUE
    selected = _select_choice("Default model", model_choices, default=default)
    if selected == CUSTOM_MODEL_VALUE:
        while True:
            model = _prompt_required("Model name", default=current_model if current_model else None)
            error = _known_provider_model_error(provider, model)
            if not error:
                return model
            console.print(f"[yellow]{error}[/yellow]")
    return selected


def _select_skill_targets(detected_targets: list[object], detected_keys: list[str]) -> list[str]:
    if _interactive_terminal():
        choices = [
            Choice(
                title=f"{target.label} ({target.key}) -> {target.root}",
                value=target.key,
                checked=target.key in detected_keys,
            )
            for target in detected_targets
        ]
        answer = questionary.checkbox(
            "Install skills into which agents?",
            choices=choices,
            instruction="Use up/down, space to select, enter to confirm.",
            validate=lambda selected: bool(selected) or "Select at least one agent.",
            style=ONBOARDING_STYLE,
        ).ask()
        if answer is None:
            raise typer.Exit(130)
        return [str(value) for value in answer]

    while True:
        default_selection = "detected" if detected_keys else ""
        raw = typer.prompt(
            "Install skills into which targets? (detected, all, or comma-separated keys)",
            default=default_selection,
            show_default=bool(default_selection),
        )
        selected = _parse_target_selection(raw, detected_keys)
        if selected:
            return selected
        console.print("[yellow]Select at least one agent target.[/yellow]")


def _prompt_required(message: str, *, default: str | None = None, hide_input: bool = False) -> str:
    while True:
        value = typer.prompt(
            message,
            default=default or "",
            hide_input=hide_input,
            show_default=default is not None,
        ).strip()
        if value:
            return value
        console.print("[yellow]This value is required.[/yellow]")


def _prompt_masked_secret(message: str, *, required: bool = False) -> str:
    if _interactive_terminal():
        answer = questionary.password(
            message,
            validate=(lambda value: bool(value.strip()) or "This value is required.") if required else None,
            style=ONBOARDING_STYLE,
        ).ask()
        if answer is None:
            raise typer.Exit(130)
        return answer.strip()
    return typer.prompt(message, default="", hide_input=True, show_default=False).strip()


def _prompt_secret(label: str, *, existing: bool, required: bool = False) -> str | None:
    suffix = " (leave blank to keep existing)" if existing else (" (required)" if required else " (optional)")
    while True:
        value = _prompt_masked_secret(f"{label}{suffix}", required=required and not existing)
        if value or not required or existing:
            break
        console.print(f"[yellow]{label} is required.[/yellow]")
    return value or None


def _configure_llm_interactive(root: Path) -> dict[str, str | bool]:
    paths = ensure_workspace(root)
    existing_config = read_toml(paths.config_file)
    existing_secrets = read_toml(paths.secrets_file)
    console.print("\n[bold bright_cyan]Model provider[/bold bright_cyan]")
    current_provider = str(_nested_value(existing_config, "llm.provider", "openai"))
    selected_provider = _select_choice(
        "LLM provider",
        LLM_PROVIDER_CHOICES,
        default=current_provider if _provider_choice(current_provider) else "openai",
    )
    selected_base_url = _provider_base_url(
        selected_provider,
        str(_nested_value(existing_config, "llm.base_url", "")) or None,
    )
    if selected_provider == "custom":
        selected_base_url = _prompt_required("LLM base URL", default=selected_base_url)
    current_model = str(_nested_value(existing_config, "llm.model", ""))
    selected_model = _select_model(selected_provider, current_model)
    selected_llm_key = _prompt_secret(
        "LLM API key",
        existing=bool(_nested_value(existing_secrets, "llm.api_key", "")),
        required=True,
    )

    update_config_value(root, "llm.provider", selected_provider, secret=False)
    update_config_value(root, "llm.base_url", selected_base_url, secret=False)
    update_config_value(root, "llm.model", selected_model, secret=False)
    if selected_llm_key:
        update_config_value(root, "llm.api_key", selected_llm_key, secret=True)
    get_settings.cache_clear()
    return {
        "provider": selected_provider,
        "base_url": selected_base_url,
        "model": selected_model,
        "api_key_updated": bool(selected_llm_key),
    }


def _parse_target_selection(raw: str, detected: list[str]) -> list[str]:
    normalized = raw.strip().lower()
    if not normalized or normalized == "none":
        return []
    if normalized == "all":
        return [target.key for target in detect_targets()]
    if normalized == "detected":
        return detected
    return [item.strip() for item in raw.split(",") if item.strip()]


@app.command("version")
def version(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show installed CLI, skill bundle, and schema versions."""
    settings = get_settings()
    payload = {
        "product": "leads",
        "cli_version": _installed_cli_version(),
        "skill_bundle_version": SKILL_BUNDLE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "workspace": str(settings.company_discovery_home),
    }
    if json_output:
        console.print_json(data=payload)
        return

    table = Table(title="leads version", show_header=True, header_style="bold")
    table.add_column("Component")
    table.add_column("Version")
    table.add_row("CLI", payload["cli_version"])
    table.add_row("Skill bundle", payload["skill_bundle_version"])
    table.add_row("DB schema", str(payload["schema_version"]))
    table.add_row("Workspace", payload["workspace"])
    console.print(table)


@app.command("doctor")
def doctor() -> None:
    """Check local workspace, configuration, and database readiness."""
    settings = get_settings()
    paths = ensure_workspace(settings.company_discovery_home)
    checks = [
        ("Workspace", paths.root.exists(), paths.root),
        ("Config", paths.config_file.exists(), paths.config_file),
        ("Secrets", paths.secrets_file.exists(), paths.secrets_file),
        ("Runtime metadata", paths.runtime_file.exists(), paths.runtime_file),
        ("Database directory", paths.data_dir.exists(), paths.data_dir),
        ("Runs directory", paths.runs_dir.exists(), paths.runs_dir),
        ("Specs directory", paths.specs_dir.exists(), paths.specs_dir),
        ("Backups directory", paths.backups_dir.exists(), paths.backups_dir),
        ("Logs directory", paths.logs_dir.exists(), paths.logs_dir),
        ("Log file", (paths.logs_dir / "leads.log").exists(), paths.logs_dir / "leads.log"),
        ("Skills directory", paths.skills_dir.exists(), paths.skills_dir),
        ("LLM API key", bool(settings.llm_api_key), "configured" if settings.llm_api_key else "missing"),
        ("Exa API key", bool(settings.exa_api_key), "configured" if settings.exa_api_key else "optional"),
        (
            "Apollo API key",
            bool(settings.apollo_api_key),
            "configured" if settings.apollo_api_key else "optional",
        ),
    ]
    table = Table(title="leads doctor", show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]ok[/green]" if ok else "[yellow]attention[/yellow]", str(detail))
    console.print(table)


@app.command("update")
def update(
    check: Annotated[bool, typer.Option("--check", help="Inspect update requirements.")] = False,
    apply_update: Annotated[
        bool,
        typer.Option("--apply", help="Apply workspace-local update steps after reviewing the plan."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
    remote: Annotated[
        bool,
        typer.Option("--remote/--no-remote", help="Check the remote release manifest when available."),
    ] = True,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip interactive confirmations.")] = False,
) -> None:
    """Guide or inspect the safe update workflow."""
    settings = get_settings()
    if check:
        plan = build_update_check(settings, remote=remote)
        if json_output:
            console.print_json(data=plan)
            return
        _render_update_plan(plan)
        return

    if apply_update:
        result = _apply_update(settings, remote=remote, yes=yes)
        if json_output:
            console.print_json(data=result)
            return
        console.print(
            Panel(
                "\n".join(f"{key}: {value}" for key, value in result.items()),
                title="Update apply complete",
                border_style="bright_green",
            )
        )
        return

    console.print(
        Panel(
            "We suggest updating this tool through one of your installed agents.\n\n"
            "Why:\n"
            "- the update may include CLI changes\n"
            "- skills may need to be updated\n"
            "- the database may need migration\n"
            "- your agent can inspect the update plan and explain what will happen before applying changes\n\n"
            "Suggested flow:\n"
            "1. `leads update --check`\n"
            "2. If CLI upgrade is needed, rerun the public installer "
            "(`curl -fsSL https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.sh | bash` "
            "on macOS/Linux, or "
            "`irm https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.ps1 | iex` "
            "on Windows)\n"
            "3. `leads update --check`\n"
            "4. ask for confirmation before structural changes, then run "
            "`leads update --apply` after reviewing migrations/backups/skill syncs.",
            title="Safe leads update",
            border_style="bright_cyan",
        )
    )


def _render_update_plan(plan: dict[str, object]) -> None:
    table = Table(title="leads update check", show_header=True, header_style="bold")
    table.add_column("Area")
    table.add_column("Installed")
    table.add_column("Target")
    table.add_column("Action")
    table.add_row(
        "CLI",
        str(plan["installed_cli_version"]),
        str(plan["latest_cli_version"]),
        "upgrade" if plan["cli_update_required"] else "none",
    )
    table.add_row(
        "Skills",
        str(plan["installed_skill_bundle_version"] or "not installed"),
        str(plan["target_skill_bundle_version"]),
        "sync" if plan["skills_update_required"] else "none",
    )
    table.add_row(
        "DB schema",
        str(plan["current_db_schema_version"]),
        str(plan["target_db_schema_version"]),
        "migrate" if plan["migration_required"] else "none",
    )
    console.print(table)
    console.print(f"Manifest source: [bold]{plan['manifest_source']}[/bold]")
    if plan.get("manifest_error"):
        console.print(f"[yellow]Remote manifest unavailable:[/yellow] {plan['manifest_error']}")
    console.print(f"Backup required: [bold]{'yes' if plan['backup_required'] else 'no'}[/bold]")
    console.print(
        f"User confirmation required: [bold]{'yes' if plan['confirmation_required'] else 'no'}[/bold]"
    )
    console.print(f"Risk summary: {plan['risk_summary']}")
    next_steps = plan.get("next_steps")
    if isinstance(next_steps, list):
        console.print("[bold]Next steps[/bold]")
        for step in next_steps:
            console.print(f"  - {step}")


def _apply_update(settings: Settings, *, remote: bool, yes: bool) -> dict[str, object]:
    plan = build_update_check(settings, remote=remote)
    if plan["cli_update_required"]:
        console.print(
            Panel(
                "A newer CLI package is available. Upgrade the package first, then rerun "
                "`leads update --check` and `leads update --apply`.\n\n"
                "Recommended commands:\n"
                "macOS/Linux: curl -fsSL https://raw.githubusercontent.com/paolo-auletta/"
                "leads-cli/main/install.sh | bash\n"
                "Windows: irm https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/"
                "install.ps1 | iex",
                title="CLI upgrade required",
                border_style="yellow",
            )
        )
        raise typer.Exit(2)

    migration_result: dict[str, object] | None = None
    if plan["migration_required"]:
        status = migration_status(settings)
        if not status.can_apply:
            _render_migration_status(status.as_dict(), json_output=False)
            raise typer.Exit(2)
        if status.backup_required and not yes:
            confirmed = typer.confirm(
                "This update will create a timestamped database backup before migrating. Continue?",
                default=False,
            )
            if not confirmed:
                console.print("Update cancelled; nothing was changed.")
                raise typer.Exit(1)
        migration_result = apply_migrations(settings)

    skills_result: dict[str, object] | None = None
    if plan["skills_update_required"]:
        selected = installed_target_keys(settings.company_discovery_home)
        if selected:
            skills_result = install_skills(settings.company_discovery_home, selected)
        else:
            skills_result = {"installs": [], "message": "No previous skill installs found."}

    final_plan = build_update_check(settings, remote=False)
    return {
        "migration": migration_result["action"] if migration_result else "none",
        "skills": "reinstalled" if skills_result else "none",
        "skills_installed_targets": [
            install.get("target")
            for install in (skills_result or {}).get("installs", [])
            if isinstance(install, dict)
        ],
        "current_cli_version": final_plan["installed_cli_version"],
        "current_skill_bundle_version": final_plan["installed_skill_bundle_version"],
        "current_db_schema_version": final_plan["current_db_schema_version"],
    }


@app.command("migrate")
def migrate(
    check: Annotated[bool, typer.Option("--check", help="Inspect database migration status.")] = False,
    apply_migration: Annotated[
        bool,
        typer.Option("--apply", help="Apply the safe migration path when one is available."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip interactive confirmation.")] = False,
) -> None:
    """Inspect or apply local database schema migrations."""
    if check and apply_migration:
        console.print("[bold red]Choose either --check or --apply, not both.[/bold red]")
        raise typer.Exit(2)

    settings = get_settings()
    status = migration_status(settings)
    if check or not apply_migration:
        _render_migration_status(status.as_dict(), json_output=json_output)
        return

    if not status.can_apply:
        _render_migration_status(status.as_dict(), json_output=json_output)
        raise typer.Exit(2)
    if status.backup_required and not yes:
        confirmed = typer.confirm(
            "This migration will create a timestamped database backup before applying. Continue?",
            default=False,
        )
        if not confirmed:
            console.print("Migration cancelled; nothing was changed.")
            return
    try:
        result = apply_migrations(settings)
    except MigrationError as exc:
        console.print(f"[bold red]Migration failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    if json_output:
        console.print_json(data=result)
        return
    console.print(
        Panel(
            f"Action: [bold]{result['action']}[/bold]\n"
            f"Schema: {result['current_schema_version']} -> {result['target_schema_version']}\n"
            f"Backup: {result['backup_path'] or 'not required'}",
            title="Migration complete",
            border_style="bright_green",
        )
    )


def _render_migration_status(plan: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        console.print_json(data=plan)
        return
    table = Table(title="leads migrate check", show_header=True, header_style="bold")
    table.add_column("Area")
    table.add_column("Current")
    table.add_column("Target")
    table.add_column("Action")
    table.add_row(
        "DB schema",
        str(plan["current_schema_version"]),
        str(plan["target_schema_version"]),
        str(plan["action"]),
    )
    table.add_row(
        "Database",
        "present" if plan["database_exists"] else "missing",
        str(plan["database_path"] or "not sqlite"),
        "backup" if plan["backup_required"] else "none",
    )
    console.print(table)
    console.print(f"Can apply: [bold]{'yes' if plan['can_apply'] else 'no'}[/bold]")
    console.print(f"Risk summary: {plan['risk_summary']}")
    console.print(f"Major-version behavior: {plan['major_version_behavior']}")


@config_app.command("show")
def config_show(
    reveal_secrets: Annotated[
        bool,
        typer.Option("--reveal-secrets", help="Show secret values instead of masking them."),
    ] = False,
) -> None:
    """Show local workspace configuration."""
    settings = get_settings()
    paths = ensure_workspace(settings.company_discovery_home)
    data = merge_dicts(read_toml(paths.config_file), read_toml(paths.secrets_file))
    console.print_json(data=data if reveal_secrets else _mask_secrets(data))


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set a non-secret local configuration value, such as llm.model."""
    settings = get_settings()
    target = update_config_value(settings.company_discovery_home, key, value, secret=False)
    get_settings.cache_clear()
    console.print(f"Updated [bold]{key}[/bold] in [bold]{target}[/bold].")


@config_app.command("set-secret")
def config_set_secret(
    key: str,
    value: Annotated[str | None, typer.Option("--value", help="Secret value. Prompts if omitted.")] = None,
) -> None:
    """Set a secret local configuration value, such as llm.api_key."""
    settings = get_settings()
    secret_value = value if value is not None else _prompt_masked_secret(f"Value for {key}", required=True)
    target = update_config_value(settings.company_discovery_home, key, secret_value, secret=True)
    get_settings.cache_clear()
    console.print(f"Updated secret [bold]{key}[/bold] in [bold]{target}[/bold].")


@config_app.command("rotate-apollo-webhook")
def config_rotate_apollo_webhook(
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Webhook.site base URL to create tokens against."),
    ] = WEBHOOK_SITE_BASE_URL,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON."),
    ] = False,
) -> None:
    """Create a fresh Webhook.site URL and configure it for Apollo phone enrichment."""
    settings = get_settings()
    try:
        token_id, webhook_url = _create_webhook_site_url(base_url)
    except httpx.HTTPStatusError as exc:
        detail = "Webhook.site token creation failed"
        if exc.response.status_code == 429:
            detail = "Webhook.site token creation is rate limited; reuse the current URL or retry later"
        console.print(f"[bold red]{detail}[/bold red]")
        raise typer.Exit(1) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        console.print(f"[bold red]Webhook.site token creation failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    target = update_config_value(
        settings.company_discovery_home,
        "providers.apollo.webhook_url",
        webhook_url,
        secret=False,
    )
    get_settings.cache_clear()
    payload = {
        "provider": "webhook.site",
        "token_id": token_id,
        "webhook_url": "********",
        "target": str(target),
    }
    if json_output:
        console.print_json(data=payload)
        return
    token_label = token_id or "created"
    console.print(
        f"Created Webhook.site token [bold]{token_label}[/bold] and updated "
        "[bold]providers.apollo.webhook_url[/bold]."
    )


@config_app.command("llm")
def config_llm() -> None:
    """Interactively update the LLM provider, model, base URL, and API key."""
    settings = get_settings()
    result = _configure_llm_interactive(settings.company_discovery_home)
    table = Table(title="LLM configuration updated", show_header=True, header_style="bold")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("Provider", str(result["provider"]))
    table.add_row("Model", str(result["model"]))
    table.add_row("Base URL", str(result["base_url"]))
    table.add_row("API key", "updated" if result["api_key_updated"] else "kept existing")
    console.print(table)


@skills_app.command("list-targets")
def skills_list_targets(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List supported agent skill installation targets."""
    targets = [
        {
            "target": target.key,
            "label": target.label,
            "path": str(target.root),
            "detected": target.detected,
        }
        for target in detect_targets()
    ]
    if json_output:
        console.print_json(data={"targets": targets})
        return
    table = Table(title="Skill targets", show_header=True, header_style="bold")
    table.add_column("Target")
    table.add_column("Detected")
    table.add_column("Path")
    for target in targets:
        table.add_row(
            f"{target['label']} ({target['target']})",
            "yes" if target["detected"] else "no",
            target["path"],
        )
    console.print(table)


@skills_app.command("status")
def skills_status(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show bundled skill and per-target install status."""
    settings = get_settings()
    status = skill_status(settings.company_discovery_home)
    if json_output:
        console.print_json(data=status)
        return
    table = Table(title="Skill install status", show_header=True, header_style="bold")
    table.add_column("Target")
    table.add_column("Detected")
    table.add_column("Installed")
    table.add_column("Path")
    for target in status["targets"]:
        table.add_row(
            f"{target['label']} ({target['target']})",
            "yes" if target["detected"] else "no",
            "yes" if target["installed"] else "no",
            target["path"],
        )
    console.print(f"Bundled skill version: [bold]{SKILL_BUNDLE_VERSION}[/bold]")
    console.print(table)


@skills_app.command("install")
def skills_install(
    targets: Annotated[
        list[str],
        typer.Option("--target", help="Target to install into. Repeat for multiple targets."),
    ] = [],
) -> None:
    """Install bundled skills into selected agent targets."""
    settings = get_settings()
    selected = targets or [target.key for target in detect_targets() if target.detected]
    if not selected:
        console.print("[yellow]No detected skill targets. Pass --target to choose one explicitly.[/yellow]")
        return
    metadata = install_skills(settings.company_discovery_home, selected)
    console.print(
        Panel(
            "\n".join(
                f"{install['label']}: {install['path']}"
                for install in metadata["installs"]
                if install["target"] in selected
            ),
            title="Skills installed",
            border_style="bright_green",
        )
    )


@skills_app.command("reinstall")
def skills_reinstall() -> None:
    """Reinstall skills into previously installed targets."""
    settings = get_settings()
    selected = installed_target_keys(settings.company_discovery_home)
    if not selected:
        console.print("[yellow]No previous skill installs found. Use leads skills install first.[/yellow]")
        return
    metadata = install_skills(settings.company_discovery_home, selected)
    console.print(
        Panel(
            "\n".join(
                f"{install['label']}: {install['path']}"
                for install in metadata["installs"]
                if install["target"] in selected
            ),
            title="Skills reinstalled",
            border_style="bright_green",
        )
    )


@app.command("init")
def init(
    workspace: Annotated[Path | None, typer.Option("--workspace", help="Workspace root.")] = None,
    llm_provider: Annotated[str, typer.Option("--llm-provider")] = "openai",
    llm_model: Annotated[str, typer.Option("--llm-model")] = "gpt-5-mini",
    llm_api_key: Annotated[str | None, typer.Option("--llm-api-key")] = None,
    exa_api_key: Annotated[str | None, typer.Option("--exa-api-key")] = None,
    apollo_api_key: Annotated[str | None, typer.Option("--apollo-api-key")] = None,
    apollo_webhook_url: Annotated[str | None, typer.Option("--apollo-webhook-url")] = None,
    targets: Annotated[
        list[str],
        typer.Option("--target", help="Skill target to install. Repeat for multiple targets."),
    ] = [],
    skip_skills: Annotated[bool, typer.Option("--skip-skills", help="Do not install agent skills.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept defaults for non-secret prompts.")] = False,
) -> None:
    """Create or repair the local leads workspace and first-run configuration."""
    env_workspace = os.getenv("LEADS_HOME") or os.getenv("COMPANY_DISCOVERY_HOME")
    if workspace:
        root = workspace.expanduser()
    elif env_workspace:
        root = Path(env_workspace).expanduser()
    else:
        root = default_workspace_root()
    if workspace is None and not yes:
        console.print(
            Panel(
                "This wizard will create one local workspace, configure your model provider, "
                "set optional data providers, install agent skills, and initialize the local database.",
                title="Welcome to leads",
                border_style="bright_cyan",
            )
        )
        root = _select_workspace_root(root)

    paths = ensure_workspace(root)
    configure_workspace_logging(root)
    write_workspace_pointer(root)
    existing_config = read_toml(paths.config_file)
    existing_secrets = read_toml(paths.secrets_file)

    selected_provider = llm_provider
    selected_model = llm_model
    selected_base_url = _provider_base_url(
        selected_provider,
        str(_nested_value(existing_config, "llm.base_url", "")) or None,
    )
    selected_llm_key = llm_api_key
    selected_exa_key = exa_api_key
    selected_apollo_key = apollo_api_key
    selected_apollo_webhook = apollo_webhook_url
    enable_exa = bool(exa_api_key)
    enable_apollo = bool(apollo_api_key or apollo_webhook_url)

    if not yes:
        console.print("\n[bold bright_cyan]Model provider[/bold bright_cyan]")
        current_provider = str(_nested_value(existing_config, "llm.provider", selected_provider))
        selected_provider = _select_choice(
            "LLM provider",
            LLM_PROVIDER_CHOICES,
            default=current_provider if _provider_choice(current_provider) else "openai",
        )
        selected_base_url = _provider_base_url(
            selected_provider,
            str(_nested_value(existing_config, "llm.base_url", selected_base_url)),
        )
        if selected_provider == "custom":
            selected_base_url = typer.prompt("LLM base URL", default=selected_base_url)
        current_model = str(_nested_value(existing_config, "llm.model", selected_model))
        selected_model = _select_model(selected_provider, current_model)
        selected_llm_key = _prompt_secret(
            "LLM API key",
            existing=bool(_nested_value(existing_secrets, "llm.api_key", "")),
            required=True,
        )

        console.print("\n[bold bright_cyan]Search provider[/bold bright_cyan]")
        enable_exa = typer.confirm("Configure Exa for live web/company search?", default=bool(exa_api_key))
        if enable_exa:
            selected_exa_key = _prompt_secret(
                "Exa API key",
                existing=bool(_nested_value(existing_secrets, "providers.exa.api_key", "")),
            )

        console.print("\n[bold bright_cyan]Contact enrichment[/bold bright_cyan]")
        enable_apollo = typer.confirm(
            "Configure Apollo for contact email/phone enrichment?",
            default=bool(apollo_api_key or apollo_webhook_url),
        )
        if enable_apollo:
            selected_apollo_key = _prompt_secret(
                "Apollo API key",
                existing=bool(_nested_value(existing_secrets, "providers.apollo.api_key", "")),
            )
            selected_apollo_webhook = typer.prompt(
                "Apollo webhook URL for phone enrichment (blank for email-only)",
                default=str(_nested_value(existing_config, "providers.apollo.webhook_url", "")),
                show_default=False,
            ) or None

    update_config_value(root, "llm.provider", selected_provider, secret=False)
    update_config_value(root, "llm.base_url", selected_base_url, secret=False)
    update_config_value(root, "llm.model", selected_model, secret=False)
    if selected_llm_key:
        update_config_value(root, "llm.api_key", selected_llm_key, secret=True)
    update_config_value(root, "providers.exa.enabled", str(enable_exa).lower(), secret=False)
    if selected_exa_key:
        update_config_value(root, "providers.exa.api_key", selected_exa_key, secret=True)
    update_config_value(root, "providers.apollo.enabled", str(enable_apollo).lower(), secret=False)
    if selected_apollo_key:
        update_config_value(root, "providers.apollo.api_key", selected_apollo_key, secret=True)
    if selected_apollo_webhook is not None:
        update_config_value(root, "providers.apollo.webhook_url", selected_apollo_webhook, secret=False)

    database = Database(f"sqlite:///{paths.database_file.resolve()}")
    try:
        database.create_schema()
    finally:
        database.dispose()

    installed: list[dict[str, object]] = []
    if not skip_skills:
        detected_targets = detect_targets()
        detected_keys = [target.key for target in detected_targets if target.detected]
        selected_targets = targets or (detected_keys if yes else [])
        if not yes:
            console.print("\n[bold bright_cyan]Agent skills[/bold bright_cyan]")
            selected_targets = _select_skill_targets(detected_targets, detected_keys)
        if selected_targets:
            installed = install_skills(root, selected_targets)["installs"]

    status_table = Table(show_header=False, box=None, padding=(0, 1))
    status_table.add_column("Item", style="bold")
    status_table.add_column("Value")
    status_table.add_row("Workspace", str(paths.root))
    status_table.add_row("Database", str(paths.database_file))
    status_table.add_row("LLM", f"{selected_provider} / {selected_model}")
    status_table.add_row("Exa", "configured" if enable_exa else "skipped")
    status_table.add_row("Apollo", "configured" if enable_apollo else "skipped")
    status_table.add_row(
        "Skills",
        ", ".join(str(install["label"]) for install in installed) if installed else "none",
    )

    handoff = [
        "Setup complete.",
    ]
    handoff.extend(
        [
            "",
            "Now use one of those agents to find the best leads with this system.",
            "",
            "Suggested test prompt:",
            '"Use the company search spec writer and company discovery operator to create a small '
            'test spec for 10 US companies in a niche I choose, run it, and summarize the selected leads."',
        ]
    )
    console.print("\n")
    console.print(Panel(status_table, title="Configuration summary", border_style="bright_green"))
    console.print(Panel("\n".join(handoff), title="leads init", border_style="bright_green"))
    get_settings.cache_clear()


@app.command("init-db")
def init_db() -> None:
    """Create the database schema, optionally resetting an existing database."""
    settings = get_settings()
    _ensure_schema_ready(settings)
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


@contacts.command("enrich")
def enrich_contacts(
    contact_discovery_run_id: str,
    email: Annotated[
        bool,
        typer.Option("--email/--no-email", help="Request Apollo email enrichment."),
    ] = True,
    phone: Annotated[
        bool,
        typer.Option("--phone/--no-phone", help="Request Apollo phone enrichment."),
    ] = True,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Ignore fresh Apollo memory and query again."),
    ] = False,
) -> None:
    """Enrich accepted discovered contacts with Apollo email and phone data."""
    if not email and not phone:
        console.print("[bold red]Enable at least one of --email or --phone.[/bold red]")
        raise typer.Exit(2)
    database: Database | None = None
    resources: list[object] = []
    try:
        database, _, pipeline, resources = build_contact_enrichment_runtime(get_settings())
        result = pipeline.enrich(
            contact_discovery_run_id,
            options=ContactEnrichmentOptions(
                reveal_email=email,
                reveal_phone=phone,
                refresh=refresh,
            ),
            progress=RichContactEnrichmentProgressReporter(),
        )
    except Exception as exc:
        console.print(f"[bold red]Contact enrichment failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    finally:
        if database is not None:
            close_runtime(database, resources)

    console.print(
        Panel(
            f"Run [bold]{result.run_id}[/bold]\n"
            f"Ready {result.summary.ready} | Review {result.summary.review} | "
            f"Blocked {result.summary.blocked}\n"
            f"Output: {result.artifact_paths['ready']}",
            title="Contact enrichment complete",
            border_style="bright_green",
        )
    )


@contacts.command("show-enrichment")
def show_contact_enrichment(run_id: str) -> None:
    """Show counts and artifacts for an Apollo contact enrichment run."""
    database: Database | None = None
    try:
        database, repository = build_contact_enrichment_repository(get_settings())
        payload = repository.get_run(run_id)
        summary = payload["summary"]
        console.print(
            Panel(
                f"Status: {payload['status']}\n"
                f"Contact discovery run: {payload['source_contact_run_id']}\n"
                f"Contacts: {summary.get('contacts_loaded', 0)} | "
                f"Memory: {summary.get('memory_reused', 0)} | "
                f"Apollo requests: {summary.get('apollo_requests', 0)}\n"
                f"Ready: {summary.get('ready', 0)} | "
                f"Review: {summary.get('review', 0)} | "
                f"Blocked: {summary.get('blocked', 0)}",
                title=f"Contact enrichment {run_id}",
            )
        )
        if payload["artifacts"]:
            console.print_json(json.dumps(payload["artifacts"], ensure_ascii=True))
    except (ContactEnrichmentRunNotFoundError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        if database is not None:
            database.dispose()


@contacts.command("inspect-enrichment")
def inspect_contact_enrichment(
    run_id: str,
    person: Annotated[str, typer.Option("--person")],
) -> None:
    """Inspect Apollo fields, trust checks, and trace for one enriched person."""
    database: Database | None = None
    try:
        database, repository = build_contact_enrichment_repository(get_settings())
        console.print_json(
            json.dumps(repository.inspect_contact(run_id, person), ensure_ascii=True)
        )
    except (ContactEnrichmentRunNotFoundError, LookupError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        if database is not None:
            database.dispose()


@contacts.command("export-enrichment")
def export_contact_enrichment(run_id: str) -> None:
    """Regenerate Apollo contact enrichment artifacts from the stored run."""
    settings = get_settings()
    database: Database | None = None
    try:
        database, repository = build_contact_enrichment_repository(settings)
        payload = repository.get_run(run_id)
        if payload["status"] != "completed":
            raise ValueError(f"contact enrichment run {run_id} is {payload['status']}, not completed")
        summary = ContactEnrichmentSummary.model_validate(payload["summary"])
        paths = ContactEnrichmentArtifactExporter(settings.artifacts_dir).export(payload, summary)
        repository.set_artifacts(run_id, paths)
        console.print(
            f"Exported contact enrichment [bold]{run_id}[/bold] to "
            f"{Path(paths['json']).parent}"
        )
    except (ContactEnrichmentRunNotFoundError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    app()
