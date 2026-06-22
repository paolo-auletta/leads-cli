from __future__ import annotations

import json
import sqlite3

from typer.testing import CliRunner

from company_discovery.cli import app
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
    with sqlite3.connect(home / "company_memory.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "company_discovery_runs" in tables
    assert "company_enrichment_runs" in tables
    assert "contact_discovery_runs" in tables


def test_init_db_reset_archives_runs_and_starts_with_empty_runs(tmp_path, monkeypatch) -> None:
    home = tmp_path / "data"
    first = invoke_with_home(monkeypatch, home, ["init-db"])
    assert first.exit_code == 0
    with sqlite3.connect(home / "company_memory.db") as connection:
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
    with sqlite3.connect(home / "company_memory.db") as connection:
        marker = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reset_marker'"
        ).fetchone()
    assert marker is None


def test_init_db_decline_leaves_database_and_runs_untouched(tmp_path, monkeypatch) -> None:
    home = tmp_path / "data"
    first = invoke_with_home(monkeypatch, home, ["init-db"])
    assert first.exit_code == 0
    database_before = (home / "company_memory.db").read_bytes()
    old_run = home / "runs" / "keep-me.json"
    old_run.write_text("keep")

    result = invoke_with_home(monkeypatch, home, ["init-db"], input="n\n")

    assert result.exit_code == 0
    assert "nothing was changed" in result.output
    assert (home / "company_memory.db").read_bytes() == database_before
    assert old_run.read_text() == "keep"
    assert list(home.glob("runs-previousdb-*")) == []


def test_validate_spec_reports_normalized_open_modes(tmp_path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "version": 1,
                "count": 50,
                "vertical": {"mode": "known", "key": "healthcare", "label": "Healthcare"},
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
                "vertical": {"mode": "known", "key": "healthcare", "label": "Healthcare"},
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


def test_contact_discovery_is_separate_and_contact_enrichment_is_not_exposed() -> None:
    contact_help = runner.invoke(app, ["contacts", "--help"])
    discovery_help = runner.invoke(app, ["contacts", "discover", "--help"])

    assert contact_help.exit_code == 0
    assert "discover" in contact_help.output
    assert "validate-spec" in contact_help.output
    assert runner.invoke(app, ["contacts", "enrich", "anything"]).exit_code == 2
    assert discovery_help.exit_code == 0
    assert "--spec" in discovery_help.output


def test_validate_contact_spec_normalizes_roles_and_domains(tmp_path) -> None:
    spec_path = tmp_path / "contacts.json"
    spec_path.write_text(
        json.dumps(
            {
                "version": 1,
                "company_source": {
                    "enrichment_run_id": "enrichment-run-1",
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
