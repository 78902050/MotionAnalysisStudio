"""Immutable models shared by trajectory catalog, readers and GUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from collections.abc import Mapping
import math


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


Point3D = tuple[float, float, float]


@dataclass(frozen=True)
class PlaybackDiagnostic:
    code: str
    message: str


@dataclass(frozen=True)
class PlaybackTrajectory:
    frames: tuple[int, ...]
    times: tuple[float, ...]
    points: Mapping[str, tuple[Point3D, ...]]
    coordinate_unit: str
    source: TrajectorySource
    diagnostics: tuple[PlaybackDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        times = tuple(float(value) for value in self.times)
        if not frames or len(frames) != len(times):
            raise ValueError("playback frames and times must be non-empty and have equal length")
        if any(current <= previous for previous, current in zip(frames, frames[1:])):
            raise ValueError("playback frames must be strictly increasing")
        if any(not math.isfinite(value) for value in times):
            raise ValueError("playback times must be finite")
        if any(current <= previous for previous, current in zip(times, times[1:])):
            raise ValueError("playback times must be strictly increasing")
        normalized = {str(label).strip(): tuple(series) for label, series in self.points.items()}
        if not normalized or any(not label for label in normalized):
            raise ValueError("playback trajectory must contain named points")
        if any(len(series) != len(frames) for series in normalized.values()):
            raise ValueError("playback point series has wrong frame count")
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "points", normalized)
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.points)
