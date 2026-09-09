"""Three-dimensional quality audit over project-owned result layers."""

import json
import math
import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.adapters.pose2sim.pose2d_repository import inferred_keypoint_schema
from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.analysis.model import Trajectory
from app.project.manager import ProjectManager
from app.project.discovery import ExistingResultDiscovery

from .model import QualityReport
from .report_store import QualityReportStore


class QualityAuditService:
    def __init__(
        self,
        reprojection_threshold: float = 5.0,
        low_confidence_threshold: float = 0.5,
    ) -> None:
        self.reprojection_threshold = reprojection_threshold
        self.low_confidence_threshold = low_confidence_threshold
        self._project: ProjectManager | None = None
        self._issue_identities: set[tuple[object, ...]] = set()

    def analyze(
        self,
        project: ProjectManager,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> QualityReport:
        self._project = project
        self._issue_identities = set()
        issues: list[QualityIssue] = []
        inputs: dict[str, object] = {}

        calibration = self._load_layer(
            project.root / "calibration" / "normalized" / "cameras.json",
            "calibration",
            issues,
        )
        synchronization_path = project.root / "synchronization" / "mapping.json"
        synchronized_inventory = ExistingResultDiscovery.pose_frame_inventory(
            project.root,
            "pose-sync",
        )
        synchronization = (
            self._load_layer(synchronization_path, "synchronization", issues)
            if synchronization_path.is_file() or not synchronized_inventory
            else None
        )
        association_path = project.root / "pose-associated" / "results.json"
        associated_inventory = ExistingResultDiscovery.pose_frame_inventory(
            project.root,
            "pose-associated",
        )
        association = (
            self._load_layer(association_path, "pose-associated", issues)
            if association_path.is_file() or not associated_inventory
            else None
        )
        pose_3d_path = project.root / "pose-3d" / "results.json"
        trc_paths = self._select_trc_files(project.root / "pose-3d")
        pose_3d = (
            self._load_layer(pose_3d_path, "pose-3d", issues)
            if pose_3d_path.is_file() or not trc_paths
            else None
        )
        (
            pose_2d,
            keypoint_indices,
            detection_count,
            pose_2d_metrics,
            raw_person_indices,
        ) = self._load_pose_2d(
            project.root / "pose",
            issues,
            progress_callback=progress_callback,
        )

        inputs["calibration"] = self._input_summary(calibration)
        inputs["synchronization"] = (
            self._input_summary(synchronization)
            if not synchronized_inventory
            else self._pose_inventory_summary(synchronized_inventory, "Pose2Sim pose-sync")
        )
        inputs["pose_2d"] = {
            "cameras": sorted(pose_2d),
            "raw_person_indices": list(raw_person_indices),
        }
        inputs["pose_3d"] = (
            self._input_summary(pose_3d)
            if not trc_paths
            else {
                "available": True,
                "format": "TRC",
                "files": [str(path) for path in trc_paths],
            }
        )
        inputs["association"] = (
            self._input_summary(association)
            if not associated_inventory
            else self._pose_inventory_summary(
                associated_inventory,
                "Pose2Sim pose-associated",
            )
        )

        actual_people = self._manifest_people(project.manifest.get("people"))
        associated_people, track_segments = self._association_counts(association)
        metrics: dict[str, float | int | None] = {
            "actual_people_count": actual_people,
            "2d_detection_people_count": detection_count,
            "associated_people_count": associated_people,
            "track_segment_count": track_segments,
            "2d_frame_count": pose_2d_metrics["frame_count"],
            "2d_total_keypoints": pose_2d_metrics["total_keypoints"],
            "2d_low_confidence_points": pose_2d_metrics["low_confidence_points"],
            "2d_missing_keypoints": pose_2d_metrics["missing_keypoints"],
            "2d_low_confidence_threshold": self.low_confidence_threshold,
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

        elif trc_paths:
            for path in trc_paths:
                try:
                    trajectory = Trajectory.from_trc(path, coordinate_system="world")
                except (OSError, UnicodeError, ValueError) as exc:
                    self._add_issue(
                        issues,
                        kind="input_invalid",
                        severity="blocking",
                        message=f"cannot read TRC quality input: {path.name}",
                        evidence={"layer": "pose-3d", "path": str(path), "reason": str(exc)},
                    )
                    continue
                for frame_index, frame in enumerate(trajectory.frames):
                    frame_has_valid_point = False
                    for series in trajectory.points.values():
                        total += 1
                        point = series[frame_index]
                        if all(math.isfinite(value) for value in point):
                            valid += 1
                            frame_has_valid_point = True
                        else:
                            missing += 1
                    if frame_has_valid_point:
                        valid_frames.append(frame)

        metrics["3d_total_points"] = total
        metrics["3d_valid_points"] = valid
        metrics["3d_missing_points"] = missing
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

    @staticmethod
    def _select_trc_files(directory: Path) -> tuple[Path, ...]:
        if not directory.is_dir():
            return ()
        selected: dict[str, tuple[int, Path]] = {}
        for path in sorted(directory.glob("*.trc")):
            stem = path.stem
            lower = stem.casefold()
            score = 2 if "lstm" in lower else 1 if "_filt_" in lower else 0
            base = re.split(r"_filt_|_LSTM$", stem, maxsplit=1, flags=re.IGNORECASE)[0]
            current = selected.get(base)
            if current is None or score > current[0]:
                selected[base] = (score, path.resolve())
        return tuple(path for _score, path in sorted(selected.values(), key=lambda item: str(item[1]).casefold()))

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

    @staticmethod
    def _pose_inventory_summary(
        inventory: dict[str, tuple[int, ...]],
        format_name: str,
    ) -> dict[str, object]:
        return {
            "available": True,
            "format": format_name,
            "cameras": {
                camera: {
                    "frame_count": len(frames),
                    "first_frame": frames[0],
                    "last_frame": frames[-1],
                }
                for camera, frames in inventory.items()
            },
        }

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
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, int],
        int,
        dict[str, int],
        tuple[int, ...],
    ]:
        quality_metrics = {
            "frame_count": 0,
            "total_keypoints": 0,
            "low_confidence_points": 0,
            "missing_keypoints": 0,
        }
        if not directory.is_dir():
            self._add_issue(
                issues,
                kind="input_invalid",
                severity="blocking",
                message="missing quality input layer: pose",
                evidence={"layer": "pose", "path": str(directory)},
            )
            return {}, {}, 0, quality_metrics, ()
        payloads: dict[str, dict[str, Any]] = {}
        keypoint_indices: dict[str, int] = {}
        detections: set[tuple[str, int, int]] = set()
        audited_frames: set[tuple[str, int]] = set()
        paths = sorted(directory.glob("*.json"))
        paths.extend(sorted(directory.glob("*_json/*.json")))
        if progress_callback is not None:
            progress_callback(0, len(paths))
        for completed, path in enumerate(paths, start=1):
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
                if progress_callback is not None:
                    progress_callback(completed, len(paths))
                continue
            if not isinstance(value, dict):
                if progress_callback is not None:
                    progress_callback(completed, len(paths))
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
                audited_frames.add((camera, frame))
                for ordinal, person_record in enumerate(
                    self._records(frame_record.get("people"))
                ):
                    raw_index = person_record.get("raw_person_index", ordinal)
                    if (
                        not isinstance(raw_index, int)
                        or isinstance(raw_index, bool)
                        or raw_index < 0
                    ):
                        raw_index = ordinal
                    detections.add((camera, frame, raw_index))
                self._audit_legacy_pose_frame(
                    camera,
                    frame,
                    value,
                    frame_record,
                    path,
                    issues,
                    quality_metrics,
                )
            if is_pose2sim_frame:
                match = re.search(r"(\d+)$", path.stem)
                if match is None:
                    if progress_callback is not None:
                        progress_callback(completed, len(paths))
                    continue
                frame = int(match.group(1))
                people = self._records(value.get("people"))
                audited_frames.add((camera, frame))
                for raw_index, _person_record in enumerate(people):
                    detections.add((camera, frame, raw_index))
                self._audit_pose2sim_frame(
                    camera,
                    frame,
                    people,
                    path,
                    issues,
                    quality_metrics,
                )
            if progress_callback is not None:
                progress_callback(completed, len(paths))
        quality_metrics["frame_count"] = len(audited_frames)
        raw_person_indices = tuple(
            sorted({raw_index for _camera, _frame, raw_index in detections})
        )
        return (
            payloads,
            keypoint_indices,
            len(detections),
            quality_metrics,
            raw_person_indices,
        )

    def _audit_legacy_pose_frame(
        self,
        camera: str,
        frame: int,
        payload: dict[str, Any],
        frame_record: dict[str, Any],
        path: Path,
        issues: list[QualityIssue],
        metrics: dict[str, int],
    ) -> None:
        model_name = payload.get("model_name")
        model = model_name if isinstance(model_name, str) and model_name.strip() else "unknown"
        declared_names = {
            name: index
            for index, name in enumerate(payload.get("keypoint_names", []))
            if isinstance(name, str) and name.strip()
        }
        for ordinal, person_record in enumerate(self._records(frame_record.get("people"))):
            raw_index = person_record.get("raw_person_index", ordinal)
            if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
                raw_index = ordinal
            person = self._pose_person_address(person_record, raw_index)
            for keypoint_name, fallback_index, point in self._keypoints(person_record):
                source_index = declared_names.get(keypoint_name, fallback_index)
                keypoint = KeypointAddress(model, keypoint_name, source_index)
                self._audit_2d_keypoint(
                    camera,
                    frame,
                    person,
                    keypoint,
                    point.get("x"),
                    point.get("y"),
                    point.get("confidence"),
                    path,
                    issues,
                    metrics,
                )

    def _audit_pose2sim_frame(
        self,
        camera: str,
        frame: int,
        people: list[dict[str, Any]],
        path: Path,
        issues: list[QualityIssue],
        metrics: dict[str, int],
    ) -> None:
        for raw_index, person_record in enumerate(people):
            values = person_record.get("pose_keypoints_2d")
            if not isinstance(values, list) or len(values) % 3:
                self._add_issue(
                    issues,
                    kind="input_invalid",
                    severity="blocking",
                    message=f"二维 pose 关节点数组格式无效：{path.name}",
                    evidence={"layer": "pose", "path": str(path)},
                )
                continue
            model_name, names = inferred_keypoint_schema(len(values) // 3)
            person = self._pose_person_address(person_record, raw_index)
            for index, keypoint_name in enumerate(names):
                offset = index * 3
                self._audit_2d_keypoint(
                    camera,
                    frame,
                    person,
                    KeypointAddress(model_name, keypoint_name, index),
                    values[offset],
                    values[offset + 1],
                    values[offset + 2],
                    path,
                    issues,
                    metrics,
                )

    def _audit_2d_keypoint(
        self,
        camera: str,
        frame: int,
        person: PersonAddress,
        keypoint: KeypointAddress,
        x: object,
        y: object,
        confidence: object,
        path: Path,
        issues: list[QualityIssue],
        metrics: dict[str, int],
    ) -> None:
        metrics["total_keypoints"] += 1
        target = FrameAddress(camera, "raw", frame)
        base_evidence = {
            "camera": camera,
            "raw_frame": frame,
            "raw_person_index": person.raw_person_index,
            "keypoint": keypoint.keypoint_name,
            "path": str(path),
        }
        if not (
            self._finite_number(x)
            and self._finite_number(y)
            and self._finite_number(confidence)
        ):
            metrics["missing_keypoints"] += 1
            self._add_issue(
                issues,
                kind="missing",
                severity="error",
                target=target,
                person=person,
                keypoint=keypoint,
                message=(
                    f"相机 {camera} 原始帧 {frame} 人物 {person.raw_person_index or 0} "
                    f"的 {keypoint.keypoint_name} 缺少有效二维坐标或置信度"
                ),
                evidence=base_evidence,
            )
            return
        confidence_value = float(confidence)
        if confidence_value >= self.low_confidence_threshold:
            return
        metrics["low_confidence_points"] += 1
        self._add_issue(
            issues,
            kind="low_confidence",
            severity="error" if confidence_value <= 0 else "warning",
            target=target,
            person=person,
            keypoint=keypoint,
            message=(
                f"相机 {camera} 原始帧 {frame} 人物 {person.raw_person_index or 0} "
                f"的 {keypoint.keypoint_name} 置信度 {confidence_value:.3f} "
                f"低于阈值 {self.low_confidence_threshold:.3f}"
            ),
            evidence={
                **base_evidence,
                "confidence": confidence_value,
                "threshold": self.low_confidence_threshold,
            },
        )

    @staticmethod
    def _pose_person_address(value: dict[str, Any], raw_index: int) -> PersonAddress:
        project_person_id = value.get("project_person_id")
        return PersonAddress(
            project_person_id
            if isinstance(project_person_id, str) and project_person_id.strip()
            else f"raw-{raw_index}",
            value.get("track_segment_id")
            if isinstance(value.get("track_segment_id"), str)
            and value["track_segment_id"].strip()
            else None,
            raw_index,
        )

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

    def _add_issue(
        self,
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
        if identity in self._issue_identities:
            return
        self._issue_identities.add(identity)
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
