"""Contracts shared by background tasks."""

from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Literal

TaskStatus = Literal["running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class TaskRequest:
    project_id: str
    generation: int
    name: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        if not self.name.strip():
            raise ValueError("task name must not be empty")


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    project_id: str
    generation: int
    name: str
    status: TaskStatus
    value: Any = None
    error: str | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelled()


class TaskCancelled(Exception):
    """Raised by cooperative task functions when cancellation is observed."""
