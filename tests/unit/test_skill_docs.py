from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIRS = [ROOT / "skills", ROOT / "src" / "company_discovery" / "bundled_skills"]
WORKSPACE_DIRS = ["backups/", "config/", "data/", "logs/", "runs/", "skills/", "specs/"]
CORE_COMMANDS = [
    "leads init",
    "leads version",
    "leads doctor",
    "leads update --check",
    "leads migrate --check",
    "leads skills status",
]


def skill_files() -> list[Path]:
    return sorted(path for directory in SKILL_DIRS for path in directory.glob("*/SKILL.md"))


def test_all_leads_skills_include_workspace_map_and_core_commands() -> None:
    for path in skill_files():
        content = path.read_text(encoding="utf-8")
        assert "## Workspace And CLI" in content, path
        for directory in WORKSPACE_DIRS:
            assert directory in content, path
        for command in CORE_COMMANDS:
            assert command in content, path
        assert "logs/leads.log" in content, path


def test_spec_writer_skills_point_to_workspace_spec_directories() -> None:
    company_files = [
        ROOT / "skills" / "company-search-spec-writer" / "SKILL.md",
        ROOT / "src" / "company_discovery" / "bundled_skills" / "company-search-spec-writer" / "SKILL.md",
    ]
    contact_files = [
        ROOT / "skills" / "contact-search-spec-writer" / "SKILL.md",
        ROOT / "src" / "company_discovery" / "bundled_skills" / "contact-search-spec-writer" / "SKILL.md",
    ]

    for path in company_files:
        assert "specs/companies/" in path.read_text(encoding="utf-8")
    for path in contact_files:
        assert "specs/contacts/" in path.read_text(encoding="utf-8")
