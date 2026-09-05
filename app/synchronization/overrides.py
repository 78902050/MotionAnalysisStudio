"""Persistent manual synchronization overrides."""

from __future__ import annotations

import json
from pathlib import Path

from app.io.atomic import AtomicJsonStore
from app.project.manager import ProjectManager

from .model import SynchronizationOverride


class SynchronizationOverrideStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "synchronization" / "overrides.json"

    def load(self) -> tuple[SynchronizationOverride, ...]:
        if not self.path.is_file():
            return ()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("synchronization overrides must be a list")
        return tuple(
            SynchronizationOverride.from_dict(item)
            for item in value
            if isinstance(item, dict)
        )

    def save(
        self,
        override: SynchronizationOverride,
        *,
        project: ProjectManager | None = None,
    ) -> bool:
        current = self.load()
        existing = next((item for item in current if item.camera == override.camera), None)
        if existing == override:
            return False
        overrides = [item for item in current if item.camera != override.camera]
        overrides.append(override)
        AtomicJsonStore.replace(self.path, [item.to_dict() for item in overrides])
        if project is not None:
            project.invalidate_from("synchronization", "synchronization override changed")
        return True
