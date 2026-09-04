"""Data contracts for correction operations and issue dispositions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.addresses import (
    CorrectionTarget,
    FrameAddress,
    KeypointAddress,
    PersonAddress,
)

CorrectionSource = Literal["manual", "restore", "migration"]
DispositionStatus = Literal["pending", "handled", "deferred", "ignored"]


def _value_triplet(value: tuple[float, float, float], field_name: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{field_name} must contain x, y and confidence")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{field_name} must contain finite numbers")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class CorrectionOperation:
    operation_id: str
    session_id: str
    target: CorrectionTarget
    before: tuple[float, float, float]
    after: tuple[float, float, float]
    note: str
    created_at: str
    source: CorrectionSource

    def __post_init__(self) -> None:
        for name, value in (("operation_id", self.operation_id), ("session_id", self.session_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise ValueError("created_at must not be empty")
        if self.source not in {"manual", "restore", "migration"}:
            raise ValueError(f"unknown correction source: {self.source}")
        object.__setattr__(self, "before", _value_triplet(self.before, "before"))
        object.__setattr__(self, "after", _value_triplet(self.after, "after"))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "target": {
                "address": {
                    "camera": self.target.address.camera,
                    "timeline": self.target.address.timeline,
                    "frame": self.target.address.frame,
                },
                "person": {
                    "project_person_id": self.target.person.project_person_id,
                    "track_segment_id": self.target.person.track_segment_id,
                    "raw_person_index": self.target.person.raw_person_index,
                },
                "keypoint": {
                    "model_name": self.target.keypoint.model_name,
                    "keypoint_name": self.target.keypoint.keypoint_name,
                    "source_index": self.target.keypoint.source_index,
                },
            },
            "before": list(self.before),
            "after": list(self.after),
            "note": self.note,
            "created_at": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CorrectionOperation":
        target_value = value.get("target")
        if not isinstance(target_value, dict):
            raise ValueError("correction operation target must be an object")
        address_value = target_value.get("address")
        person_value = target_value.get("person")
        keypoint_value = target_value.get("keypoint")
        if not all(isinstance(item, dict) for item in (address_value, person_value, keypoint_value)):
            raise ValueError("correction operation target is incomplete")
        target = CorrectionTarget(
            FrameAddress(address_value["camera"], address_value["timeline"], address_value["frame"]),
            PersonAddress(
                person_value["project_person_id"],
                person_value.get("track_segment_id"),
                person_value.get("raw_person_index"),
            ),
            KeypointAddress(
                keypoint_value["model_name"],
                keypoint_value["keypoint_name"],
                keypoint_value.get("source_index"),
            ),
        )
        return cls(
            operation_id=value["operation_id"],
            session_id=value["session_id"],
            target=target,
            before=tuple(value["before"]),
            after=tuple(value["after"]),
            note=str(value.get("note", "")),
            created_at=value["created_at"],
            source=value["source"],
        )


@dataclass
class IssueDisposition:
    issue_id: str
    status: DispositionStatus
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.issue_id, str) or not self.issue_id.strip():
            raise ValueError("issue_id must not be empty")
        if self.status not in {"pending", "handled", "deferred", "ignored"}:
            raise ValueError(f"unknown issue disposition: {self.status}")

    def to_dict(self) -> dict[str, str]:
        return {"issue_id": self.issue_id, "status": self.status, "note": self.note}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IssueDisposition":
        return cls(value["issue_id"], value["status"], str(value.get("note", "")))
