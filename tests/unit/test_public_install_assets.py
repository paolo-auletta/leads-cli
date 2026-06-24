from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_install_shell_script_is_syntax_valid_and_bootstraps_pipx() -> None:
    script = ROOT / "install.sh"

    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    content = script.read_text(encoding="utf-8")
    assert 'LEADS_PYTHON_VERSION="${LEADS_PYTHON_VERSION:-3.13}"' in content
    assert "--fetch-python" in content
    assert "run_pipx install" in content
    assert "run_pipx reinstall" in content
    assert 'run_pipx run "${PIPX_PYTHON_ARGS[@]}" --spec "$PACKAGE_NAME" leads init' in content
    assert "leads init" in content


def test_windows_installer_bootstraps_pipx_and_runs_onboarding() -> None:
    content = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert '"3.13"' in content
    assert "--fetch-python" in content
    assert "throw \"pipx command failed" in content
    assert "Invoke-Pipx install" in content
    assert '@("reinstall")' in content
    assert '@("run") + $PipxPythonArgs' in content
    assert "leads init" in content
    assert "LEADS_SKIP_INIT" in content


def test_readme_leads_with_public_install_paths() -> None:
    content = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "curl -fsSL https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.sh | bash" in content
    assert "irm https://raw.githubusercontent.com/paolo-auletta/leads-cli/main/install.ps1 | iex" in content
    assert "pipx install --python 3.13 --fetch-python missing leads-cli" in content
    assert "leads init" in content
