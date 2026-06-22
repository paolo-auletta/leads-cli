from __future__ import annotations

import json

from typer.testing import CliRunner

from company_discovery.cli import app


runner = CliRunner()


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
