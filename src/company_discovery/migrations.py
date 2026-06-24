from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from company_discovery.db.session import Database
from company_discovery.runtime import (
    SCHEMA_VERSION,
    WorkspacePaths,
    default_runtime_metadata,
    ensure_workspace,
    read_json,
    write_json,
)
from company_discovery.settings import Settings


class MigrationError(RuntimeError):
    """Raised when a requested database migration cannot be applied safely."""


@dataclass(frozen=True)
class MigrationStatus:
    product: str
    workspace: str
    database_path: str | None
    database_exists: bool
    current_schema_version: int
    target_schema_version: int
    migration_required: bool
    backup_required: bool
    can_apply: bool
    action: str
    risk_summary: str
    major_version_behavior: str

    def as_dict(self) -> dict[str, object]:
        return {
            "product": self.product,
            "workspace": self.workspace,
            "database_path": self.database_path,
            "database_exists": self.database_exists,
            "current_schema_version": self.current_schema_version,
            "target_schema_version": self.target_schema_version,
            "migration_required": self.migration_required,
            "backup_required": self.backup_required,
            "can_apply": self.can_apply,
            "action": self.action,
            "risk_summary": self.risk_summary,
            "major_version_behavior": self.major_version_behavior,
        }


def migration_status(settings: Settings) -> MigrationStatus:
    paths = ensure_workspace(settings.company_discovery_home)
    current = _current_schema_version(paths)
    target = SCHEMA_VERSION
    database_path = settings.sqlite_database_path
    database_exists = bool(database_path and database_path.exists())
    migration_required = current != target
    backup_required = migration_required and database_exists
    can_apply = _can_apply(current, target)
    action = _action(current, target, database_exists, can_apply)
    return MigrationStatus(
        product="leads",
        workspace=str(paths.root),
        database_path=str(database_path) if database_path else None,
        database_exists=database_exists,
        current_schema_version=current,
        target_schema_version=target,
        migration_required=migration_required,
        backup_required=backup_required,
        can_apply=can_apply,
        action=action,
        risk_summary=_risk_summary(current, target, database_exists, can_apply),
        major_version_behavior=(
            "Normal schema evolution is migrate-first with a database backup before structural "
            "changes. Incompatible major-version jumps should archive the old DB and run artifacts "
            "before initializing a fresh schema."
        ),
    )


def apply_migrations(settings: Settings) -> dict[str, object]:
    status = migration_status(settings)
    if not status.can_apply:
        raise MigrationError(status.risk_summary)
    database_path = settings.sqlite_database_path
    if database_path is None:
        raise MigrationError("migrations require an on-disk SQLite database")

    paths = ensure_workspace(settings.company_discovery_home)
    backup_path = create_database_backup(paths, database_path) if status.backup_required else None
    database = Database(settings.resolved_database_url)
    try:
        for version in range(status.current_schema_version + 1, status.target_schema_version + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise MigrationError(f"no migration is available for schema version {version}")
            migration(database)
        if status.current_schema_version == status.target_schema_version:
            database.create_schema()
    finally:
        database.dispose()

    runtime = read_json(paths.runtime_file, default_runtime_metadata())
    applied_at = datetime.now(timezone.utc).isoformat()
    runtime["schema_version"] = status.target_schema_version
    runtime["last_migration"] = {
        "from_schema_version": status.current_schema_version,
        "to_schema_version": status.target_schema_version,
        "applied_at": applied_at,
        "backup_path": str(backup_path) if backup_path else None,
    }
    write_json(paths.runtime_file, runtime)
    return {
        **status.as_dict(),
        "backup_path": str(backup_path) if backup_path else None,
        "applied_at": applied_at,
        "final_schema_version": status.target_schema_version,
    }


def create_database_backup(paths: WorkspacePaths, database_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = paths.backups_dir / f"db-schema-{timestamp}"
    suffix = 1
    while backup_dir.exists():
        suffix += 1
        backup_dir = paths.backups_dir / f"db-schema-{timestamp}-{suffix}"
    backup_dir.mkdir(parents=True)
    if database_path.exists():
        shutil.copy2(database_path, backup_dir / database_path.name)
    for suffix_name in ("-wal", "-shm"):
        sidecar = database_path.with_name(f"{database_path.name}{suffix_name}")
        if sidecar.exists():
            shutil.copy2(sidecar, backup_dir / sidecar.name)
    if paths.runtime_file.exists():
        shutil.copy2(paths.runtime_file, backup_dir / paths.runtime_file.name)
    return backup_dir


def _current_schema_version(paths: WorkspacePaths) -> int:
    runtime = read_json(paths.runtime_file, default_runtime_metadata())
    try:
        return int(runtime.get("schema_version") or 0)
    except (TypeError, ValueError):
        return 0


def _can_apply(current: int, target: int) -> bool:
    if current > target:
        return False
    return all(version in MIGRATIONS for version in range(current + 1, target + 1))


def _action(current: int, target: int, database_exists: bool, can_apply: bool) -> str:
    if not can_apply:
        return "manual_review"
    if current < target:
        return "migrate"
    if not database_exists:
        return "initialize"
    return "none"


def _risk_summary(current: int, target: int, database_exists: bool, can_apply: bool) -> str:
    if current > target:
        return "Local database schema is newer than this CLI; downgrade is not supported."
    if not can_apply:
        return "No migration path is available for this schema change; manual review is required."
    if current < target and database_exists:
        return "Migration can be applied after creating a timestamped database backup."
    if current < target:
        return "Migration can be applied; no existing database file needs backup."
    if not database_exists:
        return "Database file is missing; apply will initialize the current schema."
    return "Database schema is current; no migration is required."


def _create_schema(database: Database) -> None:
    database.create_schema()


MIGRATIONS: dict[int, Callable[[Database], None]] = {
    1: _create_schema,
}
