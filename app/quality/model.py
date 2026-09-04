"""Quality report and issue-facing model objects."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue


def _frame_to_dict(address: FrameAddress | None) -> dict[str, object] | None:
    if address is None:
        return None
    return {"camera": address.camera, "timeline": address.timeline, "frame": address.frame}


def _person_to_dict(person: PersonAddress | None) -> dict[str, object] | None:
    if person is None:
        return None
    return {
        "project_person_id": person.project_person_id,
        "track_segment_id": person.track_segment_id,
        "raw_person_index": person.raw_person_index,
    }


def _keypoint_to_dict(keypoint: KeypointAddress | None) -> dict[str, object] | None:
    if keypoint is None:
        return None
    return {
        "model_name": keypoint.model_name,
        "keypoint_name": keypoint.keypoint_name,
        "source_index": keypoint.source_index,
    }


def _issue_to_dict(issue: QualityIssue) -> dict[str, object]:
    return {
        "issue_id": issue.issue_id,
        "kind": issue.kind,
        "severity": issue.severity,
        "target": _frame_to_dict(issue.target),
        "person": _person_to_dict(issue.person),
        "keypoint": _keypoint_to_dict(issue.keypoint),
        "message": issue.message,
        "evidence": issue.evidence,
        "disposition": issue.disposition,
        "modification_count": issue.modification_count,
    }


@dataclass(frozen=True)
class QualityReport:
    report_id: str
    generated_at: str
    metrics_data: dict[str, float | int | None]
    issues_data: tuple[QualityIssue, ...]
    inputs: dict[str, object]

    @classmethod
    def create(
        cls,
        report_id: str,
        metrics: dict[str, float | int | None],
        issues: tuple[QualityIssue, ...],
        inputs: dict[str, object],
    ) -> "QualityReport":
        return cls(
            report_id=report_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            metrics_data=dict(metrics),
            issues_data=tuple(issues),
            inputs=dict(inputs),
        )

    def issues(self) -> tuple[QualityIssue, ...]:
        return self.issues_data

    def metrics(self) -> dict[str, float | int | None]:
        return dict(self.metrics_data)

    def target(self, issue_id: str) -> CorrectionTarget | None:
        issue = next((item for item in self.issues_data if item.issue_id == issue_id), None)
        if issue is None or issue.target is None or issue.person is None or issue.keypoint is None:
            return None
        return CorrectionTarget(issue.target, issue.person, issue.keypoint)

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "metrics": self.metrics_data,
            "issues": [_issue_to_dict(issue) for issue in self.issues_data],
            "inputs": self.inputs,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QualityReport":
        issues: list[QualityIssue] = []
        for item in value.get("issues", []):
            if not isinstance(item, dict):
                continue
            target_value = item.get("target")
            person_value = item.get("person")
            keypoint_value = item.get("keypoint")
            target = (
                FrameAddress(target_value["camera"], target_value["timeline"], target_value["frame"])
                if isinstance(target_value, dict)
                else None
            )
            person = (
                PersonAddress(
                    person_value["project_person_id"],
                    person_value.get("track_segment_id"),
                    person_value.get("raw_person_index"),
                )
                if isinstance(person_value, dict)
                else None
            )
            keypoint = (
                KeypointAddress(
                    keypoint_value["model_name"],
                    keypoint_value["keypoint_name"],
                    keypoint_value.get("source_index"),
                )
                if isinstance(keypoint_value, dict)
                else None
            )
            issues.append(
                QualityIssue(
                    issue_id=item["issue_id"],
                    kind=item["kind"],
                    severity=item["severity"],
                    target=target,
                    person=person,
                    keypoint=keypoint,
                    message=item["message"],
                    evidence=dict(item.get("evidence", {})),
                    disposition=item.get("disposition", "pending"),
                    modification_count=item.get("modification_count", 0),
                )
            )
        metrics = value.get("metrics", {})
        return cls(
            report_id=value["report_id"],
            generated_at=value["generated_at"],
            metrics_data=dict(metrics) if isinstance(metrics, dict) else {},
            issues_data=tuple(issues),
            inputs=dict(value.get("inputs", {})),
        )
