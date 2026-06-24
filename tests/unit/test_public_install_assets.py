from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_install_shell_script_is_syntax_valid_and_bootstraps_pipx() -> None:
    script = ROOT / "install.sh"

    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    content = script.read_text(encoding="utf-8")
    assert "pipx install" in content
    assert "pipx upgrade" in content
    assert "leads init" in content


def test_windows_installer_bootstraps_pipx_and_runs_onboarding() -> None:
    content = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "Invoke-Pipx install" in content
    assert "Invoke-Pipx upgrade" in content
    assert "leads init" in content
    assert "LEADS_SKIP_INIT" in content


def test_readme_leads_with_public_install_paths() -> None:
    content = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "curl -fsSL https://raw.githubusercontent.com/paoloauletta/leads/main/install.sh | bash" in content
    assert "irm https://raw.githubusercontent.com/paoloauletta/leads/main/install.ps1 | iex" in content
    assert "pipx install leads-cli" in content
    assert "leads init" in content
