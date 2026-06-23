from __future__ import annotations

from typing import Protocol


class ContactEnrichmentProgressReporter(Protocol):
    def start(self, source_run_id: str, contacts: int) -> None: ...

    def memory(self, reused: int, pending: int) -> None: ...

    def batch(self, current: int, total: int, size: int) -> None: ...

    def poll(self, request_id: str, attempt: int) -> None: ...

    def outcome(self, name: str, outcome: str, flags: list[str]) -> None: ...

    def save(self, run_id: str) -> None: ...


class NullContactEnrichmentProgressReporter:
    def start(self, source_run_id: str, contacts: int) -> None:
        pass

    def memory(self, reused: int, pending: int) -> None:
        pass

    def batch(self, current: int, total: int, size: int) -> None:
        pass

    def poll(self, request_id: str, attempt: int) -> None:
        pass

    def outcome(self, name: str, outcome: str, flags: list[str]) -> None:
        pass

    def save(self, run_id: str) -> None:
        pass
