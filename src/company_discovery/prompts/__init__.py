from __future__ import annotations

from importlib.resources import files


def load_prompt(group: str, name: str = "system.md") -> str:
    return files("company_discovery.prompts").joinpath(group, name).read_text(encoding="utf-8")

