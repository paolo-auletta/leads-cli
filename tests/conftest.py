from __future__ import annotations

from pathlib import Path

import pytest

from company_discovery.db.repository import DiscoveryRepository
from company_discovery.db.session import Database
from company_discovery.domain.spec import CompanySearchSpec


@pytest.fixture(autouse=True)
def isolated_default_workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep tests from reading or writing the user's real persisted workspace pointer."""
    from company_discovery import cli, runtime
    from company_discovery import settings as settings_module
    from company_discovery.settings import get_settings

    default_root = tmp_path / "default-app-support"
    monkeypatch.delenv("LEADS_HOME", raising=False)
    monkeypatch.delenv("COMPANY_DISCOVERY_HOME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(settings_module, "default_workspace_root", lambda: default_root)
    monkeypatch.setattr(cli, "default_workspace_root", lambda: default_root)
    get_settings.cache_clear()
    yield default_root
    get_settings.cache_clear()


@pytest.fixture
def spec() -> CompanySearchSpec:
    return CompanySearchSpec.model_validate(
        {
            "version": 1,
            "count": 2,
            "vertical": {"key": "construction", "label": "Construction"},
            "geography": {"country": "US", "states": ["TX"]},
            "company_size": {"employee_min": 10, "employee_max": 100},
            "exclude": {
                "keywords": ["franchise"],
                "ownership_types": ["franchise"],
                "company_patterns": ["directory"],
            },
            "reserve_ratio": 0.5,
        }
    )


@pytest.fixture
def repository(tmp_path: Path) -> DiscoveryRepository:
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_schema()
    repo = DiscoveryRepository(database)
    yield repo
    database.dispose()
