"""Normalized two-dimensional pose records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PoseKeypoint:
    name: str
    x: float
    y: float
    confidence: float


@dataclass(frozen=True)
class PersonPose:
    raw_person_index: int
    project_person_id: str | None
    track_segment_id: str | None
    keypoints: tuple[PoseKeypoint, ...]


@dataclass(frozen=True)
class FramePose:
    camera: str
    frame: int
    people: tuple[PersonPose, ...]
    source_path: Path
