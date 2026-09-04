"""Semantic addresses used across motion-analysis stages."""

from dataclasses import dataclass
from typing import Literal

TimelineName = Literal["raw", "synchronized", "pose2d", "pose3d"]


@dataclass(frozen=True)
class FrameAddress:
    camera: str
    timeline: TimelineName
    frame: int

    def __post_init__(self) -> None:
        if not isinstance(self.camera, str) or not self.camera.strip():
            raise ValueError("camera must not be empty")
        if self.timeline not in {"raw", "synchronized", "pose2d", "pose3d"}:
            raise ValueError(f"unknown timeline: {self.timeline}")
        if not isinstance(self.frame, int) or isinstance(self.frame, bool) or self.frame < 0:
            raise ValueError("frame must be a non-negative integer")


@dataclass(frozen=True)
class PersonAddress:
    project_person_id: str
    track_segment_id: str | None = None
    raw_person_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.project_person_id, str) or not self.project_person_id.strip():
            raise ValueError("project_person_id must not be empty")
        if self.track_segment_id is not None and not self.track_segment_id.strip():
            raise ValueError("track_segment_id must not be empty when provided")
        if self.raw_person_index is not None and (
            not isinstance(self.raw_person_index, int)
            or isinstance(self.raw_person_index, bool)
            or self.raw_person_index < 0
        ):
            raise ValueError("raw_person_index must be non-negative when provided")


@dataclass(frozen=True)
class KeypointAddress:
    model_name: str
    keypoint_name: str
    source_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        if not isinstance(self.keypoint_name, str) or not self.keypoint_name.strip():
            raise ValueError("keypoint_name must not be empty")
        if self.source_index is not None and (
            not isinstance(self.source_index, int)
            or isinstance(self.source_index, bool)
            or self.source_index < 0
        ):
            raise ValueError("source_index must be non-negative when provided")


@dataclass(frozen=True)
class CorrectionTarget:
    address: FrameAddress
    person: PersonAddress
    keypoint: KeypointAddress
