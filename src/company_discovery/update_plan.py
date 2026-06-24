from __future__ import annotations

import json
from importlib import metadata
from importlib.resources import files
from pathlib import Path
from typing import Any

import httpx

from company_discovery import __distribution_name__, __version__
from company_discovery.runtime import SCHEMA_VERSION, ensure_workspace, read_json
from company_discovery.settings import Settings


def installed_cli_version() -> str:
    try:
        return metadata.version(__distribution_name__)
    except metadata.PackageNotFoundError:
        return __version__


def release_manifest() -> dict[str, Any]:
    manifest = files("company_discovery").joinpath("release_manifest.json")
    return json.loads(manifest.read_text(encoding="utf-8"))


def build_update_check(
    settings: Settings,
    *,
    remote: bool = True,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    paths = ensure_workspace(settings.company_discovery_home)
    bundled_manifest = release_manifest()
    manifest, manifest_source, manifest_error = _target_manifest(
        settings,
        bundled_manifest,
        remote=remote,
        client=client,
    )
    runtime = read_json(paths.runtime_file, {})
    installed_skill_bundle = runtime.get("skill_bundle_version")
    target_skill_bundle = manifest["skill_bundle_version"]
    installed_version = installed_cli_version()
    target_version = manifest["cli_version"]
    current_schema = _runtime_schema_version(runtime)
    target_schema = int(manifest["schema_version"])
    migration_required = bool(manifest.get("requires_migration")) or current_schema != target_schema
    migration_supported_by_installed_cli = target_schema <= SCHEMA_VERSION
    cli_update_required = installed_version != target_version
    skills_update_required = installed_skill_bundle != target_skill_bundle
    backup_required = migration_required
    return {
        "product": "leads",
        "workspace": str(paths.root),
        "manifest_source": manifest_source,
        "manifest_url": settings.update_manifest_url if remote else None,
        "manifest_error": manifest_error,
        "installed_cli_version": installed_version,
        "latest_cli_version": target_version,
        "cli_update_required": cli_update_required,
        "installed_skill_bundle_version": installed_skill_bundle,
        "target_skill_bundle_version": target_skill_bundle,
        "skills_update_required": skills_update_required,
        "current_db_schema_version": current_schema,
        "target_db_schema_version": target_schema,
        "migration_required": migration_required,
        "migration_supported_by_installed_cli": migration_supported_by_installed_cli,
        "backup_required": backup_required,
        "confirmation_required": (
            migration_required
            or skills_update_required
            or bool(manifest.get("breaking"))
        ),
        "breaking": bool(manifest.get("breaking")),
        "next_steps": _next_steps(
            cli_update_required=cli_update_required,
            skills_update_required=skills_update_required,
            migration_required=migration_required,
            migration_supported_by_installed_cli=migration_supported_by_installed_cli,
        ),
        "risk_summary": _risk_summary(
            cli_update_required=cli_update_required,
            skills_update_required=skills_update_required,
            migration_required=migration_required,
            migration_supported_by_installed_cli=migration_supported_by_installed_cli,
            breaking=bool(manifest.get("breaking")),
            database_path=paths.database_file,
        ),
    }


def _target_manifest(
    settings: Settings,
    bundled_manifest: dict[str, Any],
    *,
    remote: bool,
    client: httpx.Client | None,
) -> tuple[dict[str, Any], str, str | None]:
    if not remote or not settings.update_manifest_url:
        return bundled_manifest, "bundled", None
    owns_client = client is None
    http_client = client or httpx.Client(timeout=settings.update_timeout_seconds)
    try:
        response = http_client.get(settings.update_manifest_url)
        response.raise_for_status()
        manifest = response.json()
        _validate_manifest(manifest)
        return manifest, "remote", None
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        return bundled_manifest, "bundled", str(exc)
    finally:
        if owns_client:
            http_client.close()


def _runtime_schema_version(runtime: dict[str, Any]) -> int:
    raw = runtime.get("schema_version")
    if raw is None:
        return SCHEMA_VERSION
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("remote release manifest is not a JSON object")
    required = {"cli_version", "skill_bundle_version", "schema_version"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"remote release manifest is missing: {', '.join(missing)}")
    int(manifest["schema_version"])


def _next_steps(
    *,
    cli_update_required: bool,
    skills_update_required: bool,
    migration_required: bool,
    migration_supported_by_installed_cli: bool,
) -> list[str]:
    steps: list[str] = []
    if cli_update_required:
        steps.append(
            "Run the public installer again (`curl -fsSL https://raw.githubusercontent.com/"
            "paolo-auletta/leads-cli/main/install.sh | bash` on macOS/Linux, or "
            "`irm https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.ps1 | iex` "
            "on Windows), or use `pip install --upgrade leads-cli` if you installed with plain pip."
        )
    if migration_required:
        if migration_supported_by_installed_cli:
            steps.append("Run `leads migrate --check`, then `leads migrate --apply` after approval.")
        else:
            steps.append("Upgrade the CLI before applying the database migration.")
    if skills_update_required:
        steps.append("Run `leads skills reinstall` after the CLI package is current.")
    if not steps:
        steps.append("No update action is required.")
    return steps


def _risk_summary(
    *,
    cli_update_required: bool,
    skills_update_required: bool,
    migration_required: bool,
    migration_supported_by_installed_cli: bool,
    breaking: bool,
    database_path: Path,
) -> str:
    if breaking:
        return "Breaking release metadata is present; review release notes before applying anything."
    if migration_required and not migration_supported_by_installed_cli:
        return (
            "A newer database schema is required, but this installed CLI cannot apply it yet; "
            "upgrade the CLI package first."
        )
    if migration_required:
        return f"Database schema changes are required; create a backup before touching {database_path}."
    if cli_update_required or skills_update_required:
        return "Only CLI or skill bundle changes are indicated by the current manifest."
    return "No update action is required for the installed manifest."
