"""Synchronization data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.domain.addresses import TimelineName

MappingMethod = Literal["identity", "offset", "table", "timestamp"]
SynchronizationTrust = Literal[
    "verified_mapping",
    "confirmed_constant_offset",
    "filename_candidate",
    "unavailable",
]


@dataclass(frozen=True)
class FrameMapping:
    camera: str
    source_timeline: TimelineName
    target_timeline: TimelineName
    source_frame: int
    target_frame: int
    method: MappingMethod
    confidence: float | None
    source: str

    def __post_init__(self) -> None:
        if not self.camera.strip():
            raise ValueError("camera must not be empty")
        if self.source_timeline not in {"raw", "synchronized", "pose2d", "pose3d"}:
            raise ValueError(f"unknown source timeline: {self.source_timeline}")
        if self.target_timeline not in {"raw", "synchronized", "pose2d", "pose3d"}:
            raise ValueError(f"unknown target timeline: {self.target_timeline}")
        if self.source_frame < 0 or self.target_frame < 0:
            raise ValueError("mapping frames must be non-negative")
        if self.method not in {"identity", "offset", "table", "timestamp"}:
            raise ValueError(f"unknown mapping method: {self.method}")
        if not self.source.strip():
            raise ValueError("mapping source must not be empty")


@dataclass(frozen=True)
class SynchronizationOverride:
    camera: str
    source: str
    frame_delta: int | None
    mapping_path: Path | None

    def __post_init__(self) -> None:
        if not self.camera.strip():
            raise ValueError("camera must not be empty")
        if not self.source.strip():
            raise ValueError("override source must not be empty")
        if self.frame_delta is not None and (
            not isinstance(self.frame_delta, int) or isinstance(self.frame_delta, bool)
        ):
            raise ValueError("frame_delta must be an integer or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "camera": self.camera,
            "source": self.source,
            "frame_delta": self.frame_delta,
            "mapping_path": str(self.mapping_path) if self.mapping_path is not None else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "SynchronizationOverride":
        mapping_path = value.get("mapping_path")
        return cls(
            str(value["camera"]),
            str(value["source"]),
            value.get("frame_delta") if isinstance(value.get("frame_delta"), int) else None,
            Path(mapping_path) if isinstance(mapping_path, str) else None,
        )


@dataclass(frozen=True)
class SynchronizationIssue:
    severity: Literal["warning", "blocking"]
    message: str
    camera: str | None = None


@dataclass(frozen=True)
class SynchronizationReport:
    mappings: tuple[FrameMapping, ...]
    issues: tuple[SynchronizationIssue, ...]
    trust_by_camera: dict[str, SynchronizationTrust] = field(default_factory=dict)
