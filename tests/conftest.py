from __future__ import annotations

from pathlib import Path

import pytest

from company_discovery.db.repository import DiscoveryRepository
from company_discovery.db.session import Database
from company_discovery.domain.spec import CompanySearchSpec


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
