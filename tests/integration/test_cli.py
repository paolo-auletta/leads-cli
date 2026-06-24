from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from company_discovery import cli
from company_discovery.cli import LLM_PROVIDER_CHOICES, app
from company_discovery import runtime
from company_discovery import settings as settings_module
from company_discovery.settings import get_settings


runner = CliRunner()


def invoke_with_home(monkeypatch, home, args, *, input=None):
    monkeypatch.setenv("COMPANY_DISCOVERY_HOME", str(home))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        return runner.invoke(app, args, input=input)
    finally:
        get_settings.cache_clear()


def test_init_db_creates_database_schema_and_runs_directory(tmp_path, monkeypatch) -> None:
    home = tmp_path / "data"

    result = invoke_with_home(monkeypatch, home, ["init-db"])

    assert result.exit_code == 0
    assert "Created a fresh database" in result.output
    assert (home / "runs").is_dir()
    with sqlite3.connect(home / "data" / "company_memory.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "company_discovery_runs" in tables
    assert "company_enrichment_runs" in tables
    assert "contact_discovery_runs" in tables
    assert "contact_enrichment_runs" in tables
    assert "contact_enrichment_items" in tables
    assert "contact_enrichment_facts" in tables


def test_init_db_reset_archives_runs_and_starts_with_empty_runs(tmp_path, monkeypatch) -> None:
    home = tmp_path / "data"
    first = invoke_with_home(monkeypatch, home, ["init-db"])
    assert first.exit_code == 0
    with sqlite3.connect(home / "data" / "company_memory.db") as connection:
        connection.execute("CREATE TABLE reset_marker (value TEXT)")
        connection.execute("INSERT INTO reset_marker VALUES ('old database')")
    (home / "runs" / "old-result.json").write_text("old run")

    result = invoke_with_home(monkeypatch, home, ["init-db"], input="y\n")

    assert result.exit_code == 0
    assert "archive the current runs" in result.output
    archives = list(home.glob("runs-previousdb-*"))
    assert len(archives) == 1
    assert (archives[0] / "old-result.json").read_text() == "old run"
    assert list((home / "runs").iterdir()) == []
    with sqlite3.connect(home / "data" / "company_memory.db") as connection:
        marker = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reset_marker'"
        ).fetchone()
    assert marker is None


def test_init_db_decline_leaves_database_and_runs_untouched(tmp_path, monkeypatch) -> None:
    home = tmp_path / "data"
    first = invoke_with_home(monkeypatch, home, ["init-db"])
    assert first.exit_code == 0
    database_before = (home / "data" / "company_memory.db").read_bytes()
    old_run = home / "runs" / "keep-me.json"
    old_run.write_text("keep")

    result = invoke_with_home(monkeypatch, home, ["init-db"], input="n\n")

    assert result.exit_code == 0
    assert "nothing was changed" in result.output
    assert (home / "data" / "company_memory.db").read_bytes() == database_before
    assert old_run.read_text() == "keep"
    assert list(home.glob("runs-previousdb-*")) == []


def test_version_reports_workspace_and_versions(tmp_path, monkeypatch) -> None:
    result = invoke_with_home(monkeypatch, tmp_path / "leads", ["version", "--json"])

    assert result.exit_code == 0
    assert '"product": "leads"' in result.output
    assert '"skill_bundle_version"' in result.output
    assert str(tmp_path / "leads") in result.output


def test_doctor_creates_workspace_layout(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"

    result = invoke_with_home(monkeypatch, home, ["doctor"])

    assert result.exit_code == 0
    assert "leads doctor" in result.output
    assert (home / "config" / "config.toml").is_file()
    assert (home / "config" / "secrets.toml").is_file()
    assert (home / "config" / "runtime.json").is_file()
    assert (home / "data").is_dir()
    assert (home / "specs" / "companies").is_dir()
    assert (home / "specs" / "contacts").is_dir()
    assert (home / "backups").is_dir()
    assert (home / "logs").is_dir()
    assert (home / "logs" / "leads.log").is_file()
    assert (home / "skills").is_dir()


def test_config_set_and_show_masks_secrets(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"

    set_model = invoke_with_home(monkeypatch, home, ["config", "set", "llm.model", "gpt-5"])
    set_secret = invoke_with_home(
        monkeypatch,
        home,
        ["config", "set-secret", "llm.api_key", "--value", "sk-test"],
    )
    shown = invoke_with_home(monkeypatch, home, ["config", "show"])

    assert set_model.exit_code == 0
    assert set_secret.exit_code == 0
    assert shown.exit_code == 0
    assert '"model": "gpt-5"' in shown.output
    assert "sk-test" not in shown.output
    assert "********" in shown.output


def test_skills_install_records_metadata_and_copies_bundle(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"
    codex_skills = tmp_path / "codex-skills"
    monkeypatch.setenv("LEADS_CODEX_SKILLS_DIR", str(codex_skills))

    result = invoke_with_home(monkeypatch, home, ["skills", "install", "--target", "codex"])
    status = invoke_with_home(monkeypatch, home, ["skills", "status", "--json"])

    assert result.exit_code == 0
    assert "Skills installed" in result.output
    assert (codex_skills / "company-discovery-operator" / "SKILL.md").is_file()
    assert (home / "skills" / "installs.json").is_file()
    assert status.exit_code == 0
    assert '"installed": true' in status.output


def test_init_creates_workspace_database_and_selected_skills(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"
    codex_skills = tmp_path / "codex-skills"
    monkeypatch.setenv("LEADS_CODEX_SKILLS_DIR", str(codex_skills))

    result = runner.invoke(
        app,
        [
            "init",
            "--workspace",
            str(home),
            "--target",
            "codex",
            "--llm-api-key",
            "sk-test",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "Setup complete" in result.output
    assert (home / "data" / "company_memory.db").is_file()
    assert (home / "config" / "config.toml").is_file()
    assert (home / "config" / "secrets.toml").is_file()
    assert (home / "logs" / "leads.log").is_file()
    assert (codex_skills / "company-search-spec-writer" / "SKILL.md").is_file()


def test_init_persists_selected_workspace_for_later_commands(tmp_path, monkeypatch) -> None:
    default_root = tmp_path / "default-app-support"
    chosen_root = tmp_path / "Desktop" / "Leads"
    codex_skills = tmp_path / "codex-skills"
    monkeypatch.delenv("LEADS_HOME", raising=False)
    monkeypatch.delenv("COMPANY_DISCOVERY_HOME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LEADS_CODEX_SKILLS_DIR", str(codex_skills))
    monkeypatch.setattr(runtime, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(settings_module, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(cli, "default_workspace_root", lambda: default_root)
    get_settings.cache_clear()

    init_result = runner.invoke(
        app,
        [
            "init",
            "--workspace",
            str(chosen_root),
            "--target",
            "codex",
            "--llm-api-key",
            "sk-test",
            "--yes",
        ],
    )
    doctor_result = runner.invoke(app, ["doctor"])
    version_result = runner.invoke(app, ["version", "--json"])

    assert init_result.exit_code == 0
    assert doctor_result.exit_code == 0
    assert version_result.exit_code == 0
    assert f'"workspace": "{chosen_root}"' in version_result.output
    assert (chosen_root / "config" / "secrets.toml").is_file()
    assert (chosen_root / "logs" / "leads.log").is_file()
    assert not (default_root / "data").exists()
    pointer = json.loads((default_root / "config" / "workspace.json").read_text())
    assert pointer["workspace_root"] == str(chosen_root.resolve())
    get_settings.cache_clear()


def test_environment_workspace_override_wins_over_persisted_workspace(
    tmp_path,
    monkeypatch,
) -> None:
    default_root = tmp_path / "default-app-support"
    chosen_root = tmp_path / "Desktop" / "Leads"
    env_root = tmp_path / "env-workspace"
    monkeypatch.delenv("COMPANY_DISCOVERY_HOME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(settings_module, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(cli, "default_workspace_root", lambda: default_root)
    runtime.write_workspace_pointer(chosen_root)
    monkeypatch.setenv("LEADS_HOME", str(env_root))
    get_settings.cache_clear()

    result = runner.invoke(app, ["version", "--json"])

    assert result.exit_code == 0
    assert f'"workspace": "{env_root}"' in result.output
    assert (env_root / "config" / "runtime.json").is_file()
    get_settings.cache_clear()


def test_init_interactive_runs_full_onboarding_wizard(
    tmp_path,
    monkeypatch,
    isolated_default_workspace_root: Path,
) -> None:
    home = tmp_path / "leads"
    codex_skills = tmp_path / "codex-skills"
    monkeypatch.setenv("LEADS_CODEX_SKILLS_DIR", str(codex_skills))

    result = runner.invoke(
        app,
        ["init", "--workspace", str(home)],
        input=(
            "openai\n"
            "gpt-5-mini\n"
            "sk-llm\n"
            "y\n"
            "exa-key\n"
            "y\n"
            "apollo-key\n"
            "https://example.test/apollo\n"
            "codex\n"
        ),
    )

    assert result.exit_code == 0
    assert "Model provider" in result.output
    assert "Search provider" in result.output
    assert "Contact enrichment" in result.output
    assert "Agent skills" in result.output
    assert "Configuration summary" in result.output
    assert (home / "data" / "company_memory.db").is_file()
    assert (codex_skills / "leads-update-operator" / "SKILL.md").is_file()
    config = (home / "config" / "config.toml").read_text()
    secrets = (home / "config" / "secrets.toml").read_text()
    assert 'model = "gpt-5-mini"' in config
    assert "enabled = true" in config
    assert 'webhook_url = "https://example.test/apollo"' in config
    assert 'api_key = "sk-llm"' in secrets
    assert 'api_key = "exa-key"' in secrets
    assert 'api_key = "apollo-key"' in secrets
    pointer = json.loads(
        (isolated_default_workspace_root / "config" / "workspace.json").read_text()
    )
    assert pointer["workspace_root"] == str(home.resolve())


def test_init_provider_choices_match_supported_llm_adapter_surface() -> None:
    providers = {choice["key"]: choice for choice in LLM_PROVIDER_CHOICES}

    assert providers["openai"]["supported"] is True
    assert providers["deepseek"]["supported"] is True
    assert providers["anthropic"]["supported"] is True
    assert providers["google-gemini"]["supported"] is True
    assert providers["custom"]["supported"] is True
    assert "gpt-5-mini" in providers["openai"]["models"]
    assert "deepseek-chat" in providers["deepseek"]["models"]
    assert "claude-sonnet-4-6" in providers["anthropic"]["models"]
    assert "gemini-3.5-flash" in providers["google-gemini"]["models"]


def test_provider_base_urls_match_native_supported_apis() -> None:
    assert cli._provider_base_url("anthropic") == "https://api.anthropic.com/v1"
    assert cli._provider_base_url("google-gemini") == "https://generativelanguage.googleapis.com/v1beta"


def test_workspace_choices_show_actual_paths() -> None:
    recommended = Path("/tmp/recommended-leads")

    choices = cli._workspace_choices(recommended)

    assert choices[0]["key"] == "recommended"
    assert "Recommended path (/tmp/recommended-leads)" == choices[0]["label"]
    assert choices[1]["key"] == "desktop"
    assert str(Path.home() / "Desktop" / "Leads") in choices[1]["label"]
    assert choices[2]["key"] == "custom"


def test_single_select_prompt_uses_pointer_without_radio_indicator(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeQuestion:
        def ask(self):
            return "openai"

    def fake_select(*args, **kwargs):
        captured.update(kwargs)
        return FakeQuestion()

    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli.questionary, "select", fake_select)

    result = cli._select_choice("LLM provider", LLM_PROVIDER_CHOICES, default="openai")

    assert result == "openai"
    assert captured["use_indicator"] is False
    assert captured["style"] is cli.ONBOARDING_STYLE


def test_masked_secret_prompt_uses_questionary_password(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeQuestion:
        def ask(self):
            return "sk-test"

    def fake_password(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return FakeQuestion()

    monkeypatch.setattr(cli, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli.questionary, "password", fake_password)

    result = cli._prompt_masked_secret("LLM API key", required=True)

    assert result == "sk-test"
    assert captured["args"] == ("LLM API key",)
    assert captured["style"] is cli.ONBOARDING_STYLE
    assert callable(captured["validate"])


def test_update_guides_user_to_preflight(tmp_path, monkeypatch) -> None:
    result = invoke_with_home(monkeypatch, tmp_path / "leads", ["update"])

    assert result.exit_code == 0
    assert "leads update --check" in result.output
    assert "ask for confirmation" in result.output


def test_update_check_reports_machine_readable_plan(tmp_path, monkeypatch) -> None:
    result = invoke_with_home(monkeypatch, tmp_path / "leads", ["update", "--check", "--json"])

    assert result.exit_code == 0
    assert '"product": "leads"' in result.output
    assert '"latest_cli_version": "0.1.1"' in result.output
    assert '"target_skill_bundle_version": "2026.06.2"' in result.output
    assert '"migration_required": false' in result.output
    assert '"risk_summary"' in result.output


def test_migrate_check_reports_current_database_status(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"

    result = invoke_with_home(monkeypatch, home, ["migrate", "--check", "--json"])

    assert result.exit_code == 0
    assert '"product": "leads"' in result.output
    assert '"current_schema_version": 1' in result.output
    assert '"target_schema_version": 1' in result.output
    assert '"migration_required": false' in result.output
    assert '"action": "initialize"' in result.output


def test_migrate_apply_backs_up_and_updates_legacy_schema_marker(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"
    init_result = invoke_with_home(monkeypatch, home, ["init-db"])
    assert init_result.exit_code == 0
    runtime_file = home / "config" / "runtime.json"
    runtime = json.loads(runtime_file.read_text())
    runtime["schema_version"] = 0
    runtime_file.write_text(json.dumps(runtime))

    result = invoke_with_home(monkeypatch, home, ["migrate", "--apply", "--yes", "--json"])

    assert result.exit_code == 0
    assert '"action": "migrate"' in result.output
    assert '"backup_required": true' in result.output
    assert '"backup_path"' in result.output
    updated_runtime = json.loads(runtime_file.read_text())
    assert updated_runtime["schema_version"] == 1
    backup_dirs = list((home / "backups").glob("db-schema-*"))
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "company_memory.db").is_file()
    assert (backup_dirs[0] / "runtime.json").is_file()


def test_migrate_apply_refuses_newer_local_schema(tmp_path, monkeypatch) -> None:
    home = tmp_path / "leads"
    invoke_with_home(monkeypatch, home, ["doctor"])
    runtime_file = home / "config" / "runtime.json"
    runtime = json.loads(runtime_file.read_text())
    runtime["schema_version"] = 999
    runtime_file.write_text(json.dumps(runtime))

    result = invoke_with_home(monkeypatch, home, ["migrate", "--apply", "--yes"])

    assert result.exit_code == 2
    assert "Local database schema is newer than this CLI" in result.output


def test_validate_spec_reports_normalized_open_modes(tmp_path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "version": 1,
                "count": 50,
                "vertical": {"key": "healthcare", "label": "Healthcare"},
            }
        )
    )
    result = runner.invoke(app, ["companies", "validate-spec", "--spec", str(spec_path)])
    assert result.exit_code == 0
    assert "Valid company search spec" in result.output
    assert "national search mode used" in result.output
    assert "no size filter applied" in result.output


def test_validate_spec_rejects_bad_state(tmp_path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "version": 1,
                "count": 5,
                "vertical": {"key": "healthcare", "label": "Healthcare"},
                "geography": {"country": "US", "states": ["NOPE"]},
            }
        )
    )
    result = runner.invoke(app, ["companies", "validate-spec", "--spec", str(spec_path)])
    assert result.exit_code == 2
    assert "Invalid search spec" in result.output


def test_discovery_and_enrichment_are_separate_commands() -> None:
    discovery_help = runner.invoke(app, ["companies", "discover", "--help"])
    enrichment_help = runner.invoke(app, ["companies", "enrich", "--help"])

    assert discovery_help.exit_code == 0
    assert "--enrich" not in discovery_help.output
    assert enrichment_help.exit_code == 0
    assert "DISCOVERY_RUN_ID" in enrichment_help.output


def test_contact_discovery_and_enrichment_are_separate_commands() -> None:
    contact_help = runner.invoke(app, ["contacts", "--help"])
    discovery_help = runner.invoke(app, ["contacts", "discover", "--help"])
    enrichment_help = runner.invoke(app, ["contacts", "enrich", "--help"])

    assert contact_help.exit_code == 0
    assert "discover" in contact_help.output
    assert "validate-spec" in contact_help.output
    assert discovery_help.exit_code == 0
    assert "--spec" in discovery_help.output
    assert enrichment_help.exit_code == 0
    assert "CONTACT_DISCOVERY_RUN_ID" in enrichment_help.output
    assert "--phone" in enrichment_help.output


def test_validate_contact_spec_normalizes_roles_and_domains(tmp_path) -> None:
    spec_path = tmp_path / "contacts.json"
    spec_path.write_text(
        json.dumps(
            {
                "version": 1,
                "company_source": {
                    "enrichment_run_id": "company-enrich-a1b2c3d4e5f6",
                    "domains": ["https://www.acme.com/about"],
                },
                "roles": [
                    {
                        "key": "Project Manager",
                        "labels": ["Project Manager", "project manager"],
                    }
                ],
            }
        )
    )

    result = runner.invoke(app, ["contacts", "validate-spec", "--spec", str(spec_path)])

    assert result.exit_code == 0
    assert "Valid contact search spec" in result.output
    assert '"key": "project_manager"' in result.output
    assert '"acme.com"' in result.output
