"""Quality issue records and their semantic targets."""

from dataclasses import dataclass, field
from typing import Literal

from .addresses import FrameAddress, KeypointAddress, PersonAddress

IssueKind = Literal[
    "missing",
    "low_confidence",
    "reprojection",
    "camera_insufficient",
    "interpolated",
    "identity_switch",
    "mapping_missing",
    "input_invalid",
]
IssueSeverity = Literal["info", "warning", "error", "blocking"]
IssueDisposition = Literal["pending", "handled", "deferred", "ignored"]


@dataclass(frozen=True)
class QualityIssue:
    issue_id: str
    kind: IssueKind
    severity: IssueSeverity
    target: FrameAddress | None
    person: PersonAddress | None
    keypoint: KeypointAddress | None
    message: str
    evidence: dict[str, object] = field(default_factory=dict)
    disposition: IssueDisposition = "pending"
    modification_count: int = 0

    def __post_init__(self) -> None:
        if not self.issue_id.strip():
            raise ValueError("issue_id must not be empty")
        if not self.message.strip():
            raise ValueError("message must not be empty")
        if self.disposition not in {"pending", "handled", "deferred", "ignored"}:
            raise ValueError(f"unknown disposition: {self.disposition}")
        if self.modification_count < 0:
            raise ValueError("modification_count must be non-negative")
