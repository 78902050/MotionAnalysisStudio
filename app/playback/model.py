"""Immutable models shared by trajectory catalog, readers and GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TrajectoryFormat = Literal["trc", "c3d"]


@dataclass(frozen=True)
class TrajectorySource:
    path: Path
    format: TrajectoryFormat
    trial_id: str
    person_id: str
    variant: str

    def __post_init__(self) -> None:
        path = Path(self.path).resolve()
        if self.format not in {"trc", "c3d"}:
            raise ValueError(f"unsupported trajectory format: {self.format}")
        for field_name in ("trial_id", "person_id", "variant"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "path", path)

    @property
    def display_name(self) -> str:
        return f"{self.trial_id} · {self.person_id} · {self.variant} · {self.format.upper()}"
