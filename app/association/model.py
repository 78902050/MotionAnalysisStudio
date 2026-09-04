"""Semantic models for the person-association stage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

AssociationMethod = Literal["exact", "spatial", "temporal"]
AssociationIssueSeverity = Literal["warning", "blocking"]


@dataclass(frozen=True)
class SkeletonFingerprint:
    model_name: str
    keypoint_names: tuple[str, ...]
    value_hash: str

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        if not self.keypoint_names or any(not name.strip() for name in self.keypoint_names):
            raise ValueError("keypoint_names must contain non-empty names")
        if not self.value_hash.strip():
            raise ValueError("value_hash must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "keypoint_names": list(self.keypoint_names),
            "value_hash": self.value_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "SkeletonFingerprint":
        names = value.get("keypoint_names")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError("fingerprint keypoint_names must be a string list")
        return cls(str(value["model_name"]), tuple(names), str(value["value_hash"]))


@dataclass(frozen=True)
class AssociationCandidate:
    candidate_id: str
    project_person_id: str
    camera: str
    synchronized_frame: int
    raw_person_index: int
    fingerprint: SkeletonFingerprint
    score: float
    method: AssociationMethod
    explanation: str
    exact: bool

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.project_person_id.strip():
            raise ValueError("candidate IDs must not be empty")
        if not self.camera.strip():
            raise ValueError("camera must not be empty")
        if self.synchronized_frame < 0 or self.raw_person_index < 0:
            raise ValueError("candidate frame and person index must be non-negative")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("candidate score must be between 0 and 1")
        if not self.explanation.strip():
            raise ValueError("candidate explanation must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "project_person_id": self.project_person_id,
            "camera": self.camera,
            "synchronized_frame": self.synchronized_frame,
            "raw_person_index": self.raw_person_index,
            "fingerprint": self.fingerprint.to_dict(),
            "score": self.score,
            "method": self.method,
            "explanation": self.explanation,
            "exact": self.exact,
        }


@dataclass(frozen=True)
class AssociationOverride:
    override_id: str
    project_person_id: str
    camera: str
    synchronized_frame: int
    raw_person_index: int
    fingerprint: SkeletonFingerprint
    confirmed_by: str = "user"
    confirmed_at: str = ""

    def __post_init__(self) -> None:
        if not self.override_id.strip() or not self.project_person_id.strip():
            raise ValueError("override IDs must not be empty")
        if not self.camera.strip():
            raise ValueError("camera must not be empty")
        if self.synchronized_frame < 0 or self.raw_person_index < 0:
            raise ValueError("override frame and person index must be non-negative")
        if not self.confirmed_by.strip():
            raise ValueError("confirmed_by must not be empty")

    @classmethod
    def from_candidate(
        cls,
        candidate: AssociationCandidate,
        confirmed_by: str = "user",
    ) -> "AssociationOverride":
        return cls(
            override_id=f"association-{uuid4().hex}",
            project_person_id=candidate.project_person_id,
            camera=candidate.camera,
            synchronized_frame=candidate.synchronized_frame,
            raw_person_index=candidate.raw_person_index,
            fingerprint=candidate.fingerprint,
            confirmed_by=confirmed_by,
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "override_id": self.override_id,
            "project_person_id": self.project_person_id,
            "camera": self.camera,
            "synchronized_frame": self.synchronized_frame,
            "raw_person_index": self.raw_person_index,
            "fingerprint": self.fingerprint.to_dict(),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "AssociationOverride":
        fingerprint = value.get("fingerprint")
        if not isinstance(fingerprint, dict):
            raise ValueError("association override fingerprint is missing")
        return cls(
            str(value["override_id"]),
            str(value["project_person_id"]),
            str(value["camera"]),
            int(value["synchronized_frame"]),
            int(value["raw_person_index"]),
            SkeletonFingerprint.from_dict(fingerprint),
            str(value.get("confirmed_by", "user")),
            str(value.get("confirmed_at", "")),
        )


@dataclass(frozen=True)
class TrackSegment:
    segment_id: str
    project_person_id: str
    camera: str
    start_frame: int
    end_frame: int
    frame_count: int

    def __post_init__(self) -> None:
        if not self.segment_id.strip() or not self.project_person_id.strip() or not self.camera.strip():
            raise ValueError("track segment IDs must not be empty")
        if self.start_frame < 0 or self.end_frame < self.start_frame:
            raise ValueError("invalid track segment frame range")
        if self.frame_count <= 0:
            raise ValueError("track segment frame_count must be positive")


@dataclass(frozen=True)
class AssociationIssue:
    severity: AssociationIssueSeverity
    message: str
    camera: str | None = None
    synchronized_frame: int | None = None
    code: str = "association_input"

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("association issue message must not be empty")


@dataclass(frozen=True)
class AssociationReport:
    candidates: tuple[AssociationCandidate, ...]
    track_segments: tuple[TrackSegment, ...]
    issues: tuple[AssociationIssue, ...]

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == "blocking" for issue in self.issues)

    def candidates_for(
        self,
        project_person_id: str,
        camera: str,
        synchronized_frame: int,
    ) -> tuple[AssociationCandidate, ...]:
        return tuple(
            item
            for item in self.candidates
            if item.project_person_id == project_person_id
            and item.camera == camera
            and item.synchronized_frame == synchronized_frame
        )


@dataclass(frozen=True)
class MaterializeResult:
    succeeded: bool
    output_path: Path
    backup_path: Path | None
    track_segments: tuple[TrackSegment, ...] = ()
    restored: bool = False
    error: str | None = None
