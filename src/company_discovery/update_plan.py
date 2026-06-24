from __future__ import annotations

import json
from importlib import metadata
from importlib.resources import files
from pathlib import Path
from typing import Any

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


def build_update_check(settings: Settings) -> dict[str, Any]:
    paths = ensure_workspace(settings.company_discovery_home)
    manifest = release_manifest()
    runtime = read_json(paths.runtime_file, {})
    installed_skill_bundle = runtime.get("skill_bundle_version")
    target_skill_bundle = manifest["skill_bundle_version"]
    installed_version = installed_cli_version()
    target_version = manifest["cli_version"]
    current_schema = int(runtime.get("schema_version") or SCHEMA_VERSION)
    target_schema = int(manifest["schema_version"])
    migration_required = bool(manifest.get("requires_migration")) or current_schema != target_schema
    cli_update_required = installed_version != target_version
    skills_update_required = installed_skill_bundle != target_skill_bundle
    backup_required = migration_required
    return {
        "product": "leads",
        "workspace": str(paths.root),
        "installed_cli_version": installed_version,
        "latest_cli_version": target_version,
        "cli_update_required": cli_update_required,
        "installed_skill_bundle_version": installed_skill_bundle,
        "target_skill_bundle_version": target_skill_bundle,
        "skills_update_required": skills_update_required,
        "current_db_schema_version": current_schema,
        "target_db_schema_version": target_schema,
        "migration_required": migration_required,
        "backup_required": backup_required,
        "confirmation_required": migration_required or bool(manifest.get("breaking")),
        "breaking": bool(manifest.get("breaking")),
        "risk_summary": _risk_summary(
            cli_update_required=cli_update_required,
            skills_update_required=skills_update_required,
            migration_required=migration_required,
            breaking=bool(manifest.get("breaking")),
            database_path=paths.database_file,
        ),
    }


def _risk_summary(
    *,
    cli_update_required: bool,
    skills_update_required: bool,
    migration_required: bool,
    breaking: bool,
    database_path: Path,
) -> str:
    if breaking:
        return "Breaking release metadata is present; review release notes before applying anything."
    if migration_required:
        return f"Database schema changes are required; create a backup before touching {database_path}."
    if cli_update_required or skills_update_required:
        return "Only CLI or skill bundle changes are indicated by the current manifest."
    return "No update action is required for the installed manifest."
