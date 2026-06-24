from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import sys
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

PRODUCT_NAME = "leads"
DISPLAY_NAME = "Leads"
SCHEMA_VERSION = 1
SKILL_BUNDLE_VERSION = "2026.06.4"
LOGGER_NAME = "company_discovery"
WORKSPACE_POINTER_FILE = "workspace.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "response_format": "auto",
    },
    "providers": {
        "exa": {
            "enabled": False,
            "base_url": "https://api.exa.ai",
        },
        "apollo": {
            "enabled": False,
            "base_url": "https://api.apollo.io",
            "webhook_url": "",
        },
    },
    "update": {
        "manifest_url": (
            "https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/"
            "src/company_discovery/release_manifest.json"
        ),
        "timeout_seconds": 10,
    },
}

DEFAULT_SECRETS: dict[str, Any] = {
    "llm": {"api_key": ""},
    "providers": {
        "exa": {"api_key": ""},
        "apollo": {"api_key": ""},
    },
}


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    config_dir: Path
    config_file: Path
    secrets_file: Path
    runtime_file: Path
    data_dir: Path
    database_file: Path
    runs_dir: Path
    specs_dir: Path
    company_specs_dir: Path
    contact_specs_dir: Path
    backups_dir: Path
    logs_dir: Path
    skills_dir: Path
    skill_bundle_dir: Path
    skill_installs_file: Path


def default_workspace_root() -> Path:
    """Return the OS-appropriate default workspace root for leads."""
    app_name = PRODUCT_NAME if sys.platform.startswith("linux") else DISPLAY_NAME
    return Path(user_data_dir(app_name, appauthor=False, roaming=True))


def workspace_pointer_file() -> Path:
    return default_workspace_root() / "config" / WORKSPACE_POINTER_FILE


def read_workspace_pointer() -> Path | None:
    payload = read_json(workspace_pointer_file(), {})
    raw = payload.get("workspace_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def write_workspace_pointer(root: Path) -> Path:
    path = workspace_pointer_file()
    write_json(
        path,
        {
            "product": PRODUCT_NAME,
            "workspace_root": str(root.expanduser().resolve()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return path


def workspace_paths(root: Path) -> WorkspacePaths:
    root = root.expanduser()
    config_dir = root / "config"
    data_dir = root / "data"
    specs_dir = root / "specs"
    skills_dir = root / "skills"
    return WorkspacePaths(
        root=root,
        config_dir=config_dir,
        config_file=config_dir / "config.toml",
        secrets_file=config_dir / "secrets.toml",
        runtime_file=config_dir / "runtime.json",
        data_dir=data_dir,
        database_file=data_dir / "company_memory.db",
        runs_dir=root / "runs",
        specs_dir=specs_dir,
        company_specs_dir=specs_dir / "companies",
        contact_specs_dir=specs_dir / "contacts",
        backups_dir=root / "backups",
        logs_dir=root / "logs",
        skills_dir=skills_dir,
        skill_bundle_dir=skills_dir / "bundle",
        skill_installs_file=skills_dir / "installs.json",
    )


def default_runtime_metadata() -> dict[str, Any]:
    return {
        "product": PRODUCT_NAME,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "skill_bundle_version": None,
        "installs": [],
    }


def ensure_workspace(root: Path) -> WorkspacePaths:
    paths = workspace_paths(root)
    for directory in (
        paths.root,
        paths.config_dir,
        paths.data_dir,
        paths.runs_dir,
        paths.company_specs_dir,
        paths.contact_specs_dir,
        paths.backups_dir,
        paths.logs_dir,
        paths.skills_dir,
        paths.skill_bundle_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.config_file.exists():
        write_toml(paths.config_file, DEFAULT_CONFIG)
    if not paths.secrets_file.exists():
        write_toml(paths.secrets_file, DEFAULT_SECRETS)
        try:
            paths.secrets_file.chmod(0o600)
        except OSError:
            pass
    if not paths.runtime_file.exists():
        write_json(paths.runtime_file, default_runtime_metadata())
    if not paths.skill_installs_file.exists():
        write_json(paths.skill_installs_file, {"skill_bundle_version": None, "installs": []})
    return paths


def configure_workspace_logging(root: Path) -> Path:
    paths = ensure_workspace(root)
    log_file = paths.logs_dir / "leads.log"
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = str(log_file.resolve())
    for handler in list(logger.handlers):
        if getattr(handler, "baseFilename", None) == target:
            return log_file
        if isinstance(handler, RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.info("workspace logging initialized")
    return log_file


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_toml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(data), encoding="utf-8")


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default or {})
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_local_settings(root: Path) -> dict[str, Any]:
    paths = workspace_paths(root)
    config = read_toml(paths.config_file)
    secrets = read_toml(paths.secrets_file)
    values: dict[str, Any] = {}

    llm = config.get("llm", {})
    llm_secrets = secrets.get("llm", {})
    _copy(values, "llm_provider", llm.get("provider"))
    _copy(values, "llm_base_url", llm.get("base_url"))
    _copy(values, "llm_model", llm.get("model"))
    _copy(values, "llm_response_format", llm.get("response_format"))
    _copy(values, "llm_api_key", _blank_to_none(llm_secrets.get("api_key")))

    providers = config.get("providers", {})
    provider_secrets = secrets.get("providers", {})
    exa = providers.get("exa", {})
    exa_secrets = provider_secrets.get("exa", {})
    _copy(values, "exa_base_url", exa.get("base_url"))
    _copy(values, "exa_api_key", _blank_to_none(exa_secrets.get("api_key")))

    apollo = providers.get("apollo", {})
    apollo_secrets = provider_secrets.get("apollo", {})
    _copy(values, "apollo_base_url", apollo.get("base_url"))
    _copy(values, "apollo_webhook_url", _blank_to_none(apollo.get("webhook_url")))
    _copy(values, "apollo_api_key", _blank_to_none(apollo_secrets.get("api_key")))

    update = config.get("update", {})
    _copy(values, "update_manifest_url", _blank_to_none(update.get("manifest_url")))
    _copy(values, "update_timeout_seconds", update.get("timeout_seconds"))
    return values


def update_config_value(root: Path, key: str, value: Any, *, secret: bool = False) -> Path:
    paths = ensure_workspace(root)
    target = paths.secrets_file if secret else paths.config_file
    data = read_toml(target)
    set_nested_value(data, key.split("."), _coerce_value(value))
    write_toml(target, data)
    if secret:
        try:
            target.chmod(0o600)
        except OSError:
            pass
    return target


def set_nested_value(data: dict[str, Any], keys: list[str], value: Any) -> None:
    cursor = data
    for key in keys[:-1]:
        next_value = cursor.setdefault(key, {})
        if not isinstance(next_value, dict):
            raise ValueError(f"Cannot set nested key through scalar value at {key!r}")
        cursor = next_value
    cursor[keys[-1]] = value


def merge_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    scalars = {key: value for key, value in data.items() if not isinstance(value, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {_format_toml_value(value)}")
    if scalars:
        lines.append("")
    _write_toml_sections(lines, [], {key: value for key, value in data.items() if isinstance(value, dict)})
    return "\n".join(lines).rstrip() + "\n"


def _write_toml_sections(lines: list[str], prefix: list[str], sections: dict[str, Any]) -> None:
    for section, values in sections.items():
        path = [*prefix, section]
        scalars = {key: value for key, value in values.items() if not isinstance(value, dict)}
        nested = {key: value for key, value in values.items() if isinstance(value, dict)}
        if scalars:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{'.'.join(path)}]")
            for key, value in scalars.items():
                lines.append(f"{key} = {_format_toml_value(value)}")
        if nested:
            _write_toml_sections(lines, path, nested)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps("" if value is None else str(value))


def _coerce_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"
    try:
        return int(normalized)
    except ValueError:
        pass
    try:
        return float(normalized)
    except ValueError:
        return value


def _copy(values: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        values[key] = value


def _blank_to_none(value: Any) -> Any:
    if value == "":
        return None
    return value
