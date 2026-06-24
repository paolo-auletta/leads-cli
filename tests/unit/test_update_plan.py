from __future__ import annotations

import httpx

from company_discovery import __version__
from company_discovery.settings import Settings
from company_discovery.update_plan import build_update_check


def test_update_check_uses_remote_manifest_when_available(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "cli_version": "9.9.9",
                "skill_bundle_version": "2099.01.1",
                "schema_version": 2,
                "requires_migration": True,
                "breaking": False,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(
        leads_home=tmp_path / "leads",
        update_manifest_url="https://updates.example.test/release_manifest.json",
    )

    plan = build_update_check(settings, client=client)

    assert plan["manifest_source"] == "remote"
    assert plan["latest_cli_version"] == "9.9.9"
    assert plan["target_skill_bundle_version"] == "2099.01.1"
    assert plan["target_db_schema_version"] == 2
    assert plan["cli_update_required"] is True
    assert plan["migration_required"] is True
    assert plan["migration_supported_by_installed_cli"] is False
    assert "upgrade the CLI" in plan["risk_summary"]


def test_update_check_falls_back_to_bundled_manifest_when_remote_fails(tmp_path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="nope"))
    )
    settings = Settings(
        leads_home=tmp_path / "leads",
        update_manifest_url="https://updates.example.test/release_manifest.json",
    )

    plan = build_update_check(settings, client=client)

    assert plan["manifest_source"] == "bundled"
    assert plan["manifest_error"]
    assert plan["latest_cli_version"] == __version__
