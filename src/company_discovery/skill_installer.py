from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from company_discovery.runtime import (
    SKILL_BUNDLE_VERSION,
    ensure_workspace,
    read_json,
    write_json,
)


@dataclass(frozen=True)
class SkillTarget:
    key: str
    label: str
    root: Path
    detected: bool


SUPPORTED_TARGETS: dict[str, str] = {
    "codex": "Codex",
    "claude-code": "Claude Code",
    "opencode": "OpenCode",
}


def bundled_skill_names() -> list[str]:
    root = files("company_discovery.bundled_skills")
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith("__")
    )


def detect_targets() -> list[SkillTarget]:
    return [
        _target(
            "codex",
            "Codex",
            direct_env="LEADS_CODEX_SKILLS_DIR",
            base_env="CODEX_HOME",
            default_base=Path.home() / ".codex",
            child="skills",
        ),
        _target(
            "claude-code",
            "Claude Code",
            direct_env="LEADS_CLAUDE_CODE_SKILLS_DIR",
            base_env="CLAUDE_HOME",
            default_base=Path.home() / ".claude",
            child="skills",
        ),
        _target(
            "opencode",
            "OpenCode",
            direct_env="LEADS_OPENCODE_SKILLS_DIR",
            base_env="OPENCODE_CONFIG_HOME",
            default_base=Path.home() / ".config" / "opencode",
            child="skills",
        ),
    ]


def install_skills(workspace_root: Path, target_keys: list[str]) -> dict[str, Any]:
    paths = ensure_workspace(workspace_root)
    _sync_bundle(paths.skill_bundle_dir)
    targets = {target.key: target for target in detect_targets()}
    installed_at = datetime.now(timezone.utc).isoformat()
    installs: list[dict[str, Any]] = []
    for key in target_keys:
        if key not in targets:
            raise ValueError(f"Unsupported skill target: {key}")
        target = targets[key]
        target.root.mkdir(parents=True, exist_ok=True)
        for skill_name in bundled_skill_names():
            source = paths.skill_bundle_dir / skill_name
            destination = target.root / skill_name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        installs.append(
            {
                "target": key,
                "label": target.label,
                "path": str(target.root),
                "status": "ok",
                "installed_at": installed_at,
                "skills": bundled_skill_names(),
            }
        )

    metadata = read_json(paths.skill_installs_file, {"installs": []})
    prior = {
        install.get("target"): install
        for install in metadata.get("installs", [])
        if isinstance(install, dict)
    }
    for install in installs:
        prior[install["target"]] = install
    metadata = {
        "skill_bundle_version": SKILL_BUNDLE_VERSION,
        "installs": list(prior.values()),
    }
    write_json(paths.skill_installs_file, metadata)

    runtime = read_json(paths.runtime_file, {})
    runtime["skill_bundle_version"] = SKILL_BUNDLE_VERSION
    runtime["installs"] = metadata["installs"]
    write_json(paths.runtime_file, runtime)
    return metadata


def skill_status(workspace_root: Path) -> dict[str, Any]:
    paths = ensure_workspace(workspace_root)
    metadata = read_json(paths.skill_installs_file, {"skill_bundle_version": None, "installs": []})
    installed_targets = {
        install.get("target"): install
        for install in metadata.get("installs", [])
        if isinstance(install, dict)
    }
    return {
        "skill_bundle_version": metadata.get("skill_bundle_version"),
        "bundled_skills": bundled_skill_names(),
        "targets": [
            {
                "target": target.key,
                "label": target.label,
                "path": str(target.root),
                "detected": target.detected,
                "installed": target.key in installed_targets,
                "installed_at": installed_targets.get(target.key, {}).get("installed_at"),
            }
            for target in detect_targets()
        ],
    }


def installed_target_keys(workspace_root: Path) -> list[str]:
    metadata = skill_status(workspace_root)
    return [
        target["target"]
        for target in metadata["targets"]
        if target.get("installed")
    ]


def _sync_bundle(destination: Path) -> None:
    source = files("company_discovery.bundled_skills")
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name.startswith("__"):
            continue
        target = destination / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            _copy_resource_tree(child, target)


def _copy_resource_tree(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name == "__pycache__":
            continue
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())


def _target(
    key: str,
    label: str,
    *,
    direct_env: str,
    base_env: str,
    default_base: Path,
    child: str,
) -> SkillTarget:
    if os.getenv(direct_env):
        root = Path(os.environ[direct_env]).expanduser()
        return SkillTarget(key=key, label=label, root=root, detected=True)

    base = Path(os.getenv(base_env, str(default_base))).expanduser()
    root = base / child
    detected = base.exists() or root.exists() or os.getenv(base_env) is not None
    return SkillTarget(key=key, label=label, root=root, detected=detected)
