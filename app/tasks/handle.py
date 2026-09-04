"""Immediate handles for cancellable background tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import TaskResult


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    project_id: str
    generation: int
    name: str
    _cancel: Callable[[], None]
    _wait: Callable[[float | None], TaskResult]

    def cancel(self) -> None:
        self._cancel()

    def wait(self, timeout: float | None = None) -> TaskResult:
        return self._wait(timeout)
