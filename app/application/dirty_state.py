"""Common contract for editable application services and pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DirtyState:
    dirty: bool
    label: str
    detail: str = ""


class DirtyEditor(Protocol):
    def dirty_state(self) -> DirtyState: ...

    def save(self) -> bool: ...

    def discard_unsaved(self) -> None: ...


class ClosableResource(Protocol):
    def close(self) -> bool: ...
