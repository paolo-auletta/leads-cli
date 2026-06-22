from __future__ import annotations

from typing import Protocol


class EnrichmentProgressReporter(Protocol):
    def start(self, discovery_run_id: str, total: int, bucket: str) -> None: ...
    def company(self, current: int, total: int, name: str) -> None: ...
    def event(self, label: str, message: str) -> None: ...


class NullEnrichmentProgressReporter:
    def start(self, discovery_run_id: str, total: int, bucket: str) -> None:
        pass

    def company(self, current: int, total: int, name: str) -> None:
        pass

    def event(self, label: str, message: str) -> None:
        pass
