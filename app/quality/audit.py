"""Three-dimensional quality audit over project-owned result layers."""

import json
import math
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.project.manager import ProjectManager

from .model import QualityReport
from .report_store import QualityReportStore


class QualityAuditService:
    def __init__(self, reprojection_threshold: float = 5.0) -> None:
        self.reprojection_threshold = reprojection_threshold
        self._project: ProjectManager | None = None

    def analyze(self, project: ProjectManager) -> QualityReport:
        self._project = project
        issues: list[QualityIssue] = []
        inputs: dict[str, object] = {}

        calibration = self._load_layer(
            project.root / "calibration" / "normalized" / "cameras.json",
            "calibration",
            issues,
        )
        synchronization = self._load_layer(
            project.root / "synchronization" / "mapping.json",
            "synchronization",
            issues,
        )
        association = self._load_layer(
            project.root / "pose-associated" / "results.json",
            "pose-associated",
            issues,
        )
        pose_3d = self._load_layer(project.root / "pose-3d" / "results.json", "pose-3d", issues)
        pose_2d, keypoint_indices, detection_count = self._load_pose_2d(project.root / "pose", issues)

        inputs["calibration"] = self._input_summary(calibration)
        inputs["synchronization"] = self._input_summary(synchronization)
        inputs["pose_2d"] = sorted(pose_2d)
        inputs["pose_3d"] = self._input_summary(pose_3d)
        inputs["association"] = self._input_summary(association)

        actual_people = self._manifest_people(project.manifest.get("people"))
        associated_people, track_segments = self._association_counts(association)
        metrics: dict[str, float | int | None] = {
            "actual_people_count": actual_people,
            "2d_detection_people_count": detection_count,
            "associated_people_count": associated_people,
            "track_segment_count": track_segments,
        }

        total = 0
        valid = 0
        missing = 0
        interpolated = 0
        reprojection_values: list[float] = []
        participation: dict[str, int] = {}
        valid_frames: list[int] = []

        if pose_3d is not None:
            model_name = str(pose_3d.get("model_name", "unknown"))
            for frame_record in self._records(pose_3d.get("frames")):
                frame = frame_record.get("frame")
                if not isinstance(frame, int) or frame < 0:
                    self._add_issue(
                        issues,
                        kind="input_invalid",
                        severity="blocking",
                        message="pose-3d contains an invalid frame number",
                        evidence={"layer": "pose-3d", "frame": frame},
                    )
                    continue
                for person_record in self._records(frame_record.get("people")):
                    person = self._person_from_record(person_record)
                    for keypoint_name, keypoint_index, point in self._keypoints(person_record):
                        total += 1
                        if self._is_valid_point(point):
                            valid += 1
                            valid_frames.append(frame)
                        else:
                            missing += 1

                        if bool(point.get("interpolated", False)):
                            interpolated += 1
                        cameras = self._string_list(point.get("observed_cameras"))
                        for camera in cameras:
                            participation[camera] = participation.get(camera, 0) + 1

                        error_by_camera = point.get("reprojection_error_by_camera")
                        selected_camera = cameras[0] if cameras else None
                        selected_error = point.get("reprojection_error")
                        if isinstance(error_by_camera, dict):
                            numeric_errors = {
                                str(camera): float(error)
                                for camera, error in error_by_camera.items()
                                if self._finite_number(error)
                            }
                            if numeric_errors:
                                selected_camera, selected_error = max(
                                    numeric_errors.items(), key=lambda item: item[1]
                                )
                                reprojection_values.extend(numeric_errors.values())
                        elif self._finite_number(selected_error):
                            selected_error = float(selected_error)
                            reprojection_values.append(selected_error)

                        if self._finite_number(selected_error) and float(selected_error) > self.reprojection_threshold:
                            target = (
                                FrameAddress(selected_camera, "pose2d", frame)
                                if selected_camera
                                else None
                            )
                            semantic_person = PersonAddress(
                                person.project_person_id,
                                person.track_segment_id,
                                person.raw_person_index,
                            )
                            keypoint = KeypointAddress(
                                model_name,
                                keypoint_name,
                                keypoint_indices.get(keypoint_name, keypoint_index),
                            )
                            self._add_issue(
                                issues,
                                kind="reprojection",
                                severity="warning",
                                target=target,
                                person=semantic_person,
                                keypoint=keypoint,
                                message=f"reprojection error exceeds {self.reprojection_threshold:g}px",
                                evidence={
                                    "error": float(selected_error),
                                    "threshold": self.reprojection_threshold,
                                    "camera": selected_camera,
                                    "frame": frame,
                                },
                            )

        metrics["valid_keypoint_rate"] = valid / total if total else None
        metrics["missing_rate"] = missing / total if total else None
        metrics["interpolated_rate"] = interpolated / total if total else None
        metrics["average_reprojection_error"] = (
            sum(reprojection_values) / len(reprojection_values) if reprojection_values else None
        )
        metrics["participating_camera_count"] = (
            len(participation) if participation else None
        )
        metrics["coverage_start_frame"] = min(valid_frames) if valid_frames else None
        metrics["coverage_end_frame"] = max(valid_frames) if valid_frames else None
        for camera, count in sorted(participation.items()):
            metrics[f"camera_contribution.{camera}"] = count

        report_id = f"quality-{uuid4().hex[:12]}"
        return QualityReport.create(report_id, metrics, tuple(issues), inputs)

    def save(self, report: QualityReport) -> None:
        if self._project is None:
            raise RuntimeError("analyze(project) must be called before save(report)")
        QualityReportStore(self._project).save(report)

    @staticmethod
    def _manifest_people(value: object) -> int:
        if not isinstance(value, list):
            return 0
        return len({item.get("project_person_id") for item in value if isinstance(item, dict) and item.get("project_person_id")})

    @staticmethod
    def _records(value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _input_summary(value: dict[str, Any] | None) -> object:
        if value is None:
            return {"available": False}
        return {"available": True}

    def _load_layer(
        self,
        path: Path,
        layer: str,
        issues: list[QualityIssue],
    ) -> dict[str, Any] | None:
        if not path.is_file():
            self._add_issue(
                issues,
                kind="input_invalid",
                severity="blocking",
                message=f"missing quality input layer: {layer} ({path.name})",
                evidence={"layer": layer, "path": str(path)},
            )
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._add_issue(
                issues,
                kind="input_invalid",
                severity="blocking",
                message=f"cannot read quality input layer: {layer}",
                evidence={"layer": layer, "path": str(path), "reason": str(exc)},
            )
            return None
        if not isinstance(value, dict):
            self._add_issue(
                issues,
                kind="input_invalid",
                severity="blocking",
                message=f"quality input layer is not a JSON object: {layer}",
                evidence={"layer": layer, "path": str(path)},
            )
            return None
        return value

    def _load_pose_2d(
        self,
        directory: Path,
        issues: list[QualityIssue],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, int], int]:
        if not directory.is_dir():
            self._add_issue(
                issues,
                kind="input_invalid",
                severity="blocking",
                message="missing quality input layer: pose",
                evidence={"layer": "pose", "path": str(directory)},
            )
            return {}, {}, 0
        payloads: dict[str, dict[str, Any]] = {}
        keypoint_indices: dict[str, int] = {}
        detections: set[tuple[str, int, int]] = set()
        paths = sorted(directory.glob("*.json"))
        paths.extend(sorted(directory.glob("*_json/*.json")))
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._add_issue(
                    issues,
                    kind="input_invalid",
                    severity="blocking",
                    message=f"cannot read 2D pose file: {path.name}",
                    evidence={"layer": "pose", "path": str(path), "reason": str(exc)},
                )
                continue
            if not isinstance(value, dict):
                continue
            is_pose2sim_frame = path.parent != directory and path.parent.name.endswith("_json")
            camera = str(
                value.get(
                    "camera",
                    path.parent.name.removesuffix("_json") if is_pose2sim_frame else path.stem,
                )
            )
            payloads[camera] = value
            names = value.get("keypoint_names")
            if isinstance(names, list):
                for index, name in enumerate(names):
                    if isinstance(name, str):
                        keypoint_indices.setdefault(name, index)
            for frame_record in self._records(value.get("frames")):
                frame = frame_record.get("frame")
                if not isinstance(frame, int):
                    continue
                for person_record in self._records(frame_record.get("people")):
                    raw_index = person_record.get("raw_person_index")
                    if isinstance(raw_index, int) and raw_index >= 0:
                        detections.add((camera, frame, raw_index))
            if is_pose2sim_frame:
                match = re.search(r"(\d+)$", path.stem)
                if match is None:
                    continue
                frame = int(match.group(1))
                for raw_index, person_record in enumerate(self._records(value.get("people"))):
                    values = person_record.get("pose_keypoints_2d")
                    if isinstance(values, list) and values:
                        detections.add((camera, frame, raw_index))
        return payloads, keypoint_indices, len(detections)

    @staticmethod
    def _association_counts(value: dict[str, Any] | None) -> tuple[int, int]:
        if value is None:
            return 0, 0
        people: set[str] = set()
        segments: set[str] = set()
        for frame_record in QualityAuditService._records(value.get("frames")):
            for person in QualityAuditService._records(frame_record.get("people")):
                project_person_id = person.get("project_person_id")
                track_segment_id = person.get("track_segment_id")
                if isinstance(project_person_id, str) and project_person_id:
                    people.add(project_person_id)
                if isinstance(track_segment_id, str) and track_segment_id:
                    segments.add(track_segment_id)
        return len(people), len(segments)

    @staticmethod
    def _person_from_record(value: dict[str, Any]) -> PersonAddress:
        project_person_id = value.get("project_person_id")
        if not isinstance(project_person_id, str) or not project_person_id:
            project_person_id = f"unassigned-{value.get('raw_person_index', 'unknown')}"
        return PersonAddress(
            project_person_id,
            value.get("track_segment_id") if isinstance(value.get("track_segment_id"), str) else None,
            value.get("raw_person_index") if isinstance(value.get("raw_person_index"), int) else None,
        )

    @staticmethod
    def _keypoints(value: dict[str, Any]) -> list[tuple[str, int | None, dict[str, Any]]]:
        keypoints = value.get("keypoints")
        if isinstance(keypoints, dict):
            return [
                (name, None, point)
                for name, point in keypoints.items()
                if isinstance(name, str) and isinstance(point, dict)
            ]
        if isinstance(keypoints, list):
            result: list[tuple[str, int | None, dict[str, Any]]] = []
            for index, point in enumerate(keypoints):
                if isinstance(point, dict) and isinstance(point.get("name"), str):
                    result.append((point["name"], index, point))
            return result
        return []

    @staticmethod
    def _is_valid_point(value: dict[str, Any]) -> bool:
        xyz = value.get("xyz")
        confidence = value.get("confidence")
        return (
            isinstance(xyz, list)
            and len(xyz) == 3
            and all(QualityAuditService._finite_number(item) for item in xyz)
            and QualityAuditService._finite_number(confidence)
            and float(confidence) > 0
        )

    @staticmethod
    def _finite_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    @staticmethod
    def _add_issue(
        issues: list[QualityIssue],
        *,
        kind: str,
        severity: str,
        message: str,
        target: FrameAddress | None = None,
        person: PersonAddress | None = None,
        keypoint: KeypointAddress | None = None,
        evidence: dict[str, object] | None = None,
    ) -> None:
        identity = (
            kind,
            target.camera if target else None,
            target.timeline if target else None,
            target.frame if target else None,
            person.project_person_id if person else None,
            keypoint.keypoint_name if keypoint else None,
            message if target is None and person is None and keypoint is None else None,
        )
        for existing in issues:
            existing_identity = (
                existing.kind,
                existing.target.camera if existing.target else None,
                existing.target.timeline if existing.target else None,
                existing.target.frame if existing.target else None,
                existing.person.project_person_id if existing.person else None,
                existing.keypoint.keypoint_name if existing.keypoint else None,
                existing.message
                if existing.target is None and existing.person is None and existing.keypoint is None
                else None,
            )
            if existing_identity == identity:
                return
        issues.append(
            QualityIssue(
                issue_id=f"issue-{len(issues) + 1:04d}",
                kind=kind,
                severity=severity,
                target=target,
                person=person,
                keypoint=keypoint,
                message=message,
                evidence=evidence or {},
            )
        )
