from __future__ import annotations

from typing import Protocol


class ContactProgressReporter(Protocol):
    def start(self, source_run_id: str, companies: int, roles: int) -> None: ...

    def company(self, current: int, total: int, name: str, domain: str) -> None: ...

    def memory(self, role: str, reused: int, target: int) -> None: ...

    def search(self, role: str, current: int, total: int, results: int) -> None: ...

    def evaluation(self, role: str, accepted: int, review: int, rejected: int) -> None: ...

    def save(self, run_id: str) -> None: ...


class NullContactProgressReporter:
    def start(self, source_run_id: str, companies: int, roles: int) -> None:
        pass

    def company(self, current: int, total: int, name: str, domain: str) -> None:
        pass

    def memory(self, role: str, reused: int, target: int) -> None:
        pass

    def search(self, role: str, current: int, total: int, results: int) -> None:
        pass

    def evaluation(self, role: str, accepted: int, review: int, rejected: int) -> None:
        pass

    def save(self, run_id: str) -> None:
        pass

