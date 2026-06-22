from __future__ import annotations

from typing import Protocol


class ProgressReporter(Protocol):
    def stage(self, number: int, total: int, name: str, kind: str) -> None: ...

    def info(self, message: str) -> None: ...

    def detail(self, message: str) -> None: ...

    def query(self, current: int, total: int, query: str, raw_total: int) -> None: ...

    def evaluation(
        self,
        current: int,
        total: int,
        selected: int,
        reserve: int,
        rejected: int,
        detail: str | None = None,
    ) -> None: ...


class NullProgressReporter:
    def stage(self, number: int, total: int, name: str, kind: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def detail(self, message: str) -> None:
        return None

    def query(self, current: int, total: int, query: str, raw_total: int) -> None:
        return None

    def evaluation(
        self,
        current: int,
        total: int,
        selected: int,
        reserve: int,
        rejected: int,
        detail: str | None = None,
    ) -> None:
        return None
