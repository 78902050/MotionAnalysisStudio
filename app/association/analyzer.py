"""Build explainable, non-automatic person-association candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.synchronization.analyzer import SynchronizationAnalyzer

from .model import (
    AssociationCandidate,
    AssociationIssue,
    AssociationReport,
    SkeletonFingerprint,
    TrackSegment,
)


@dataclass(frozen=True)
class _Detection:
    camera: str
    frame: int
    raw_person_index: int
    points: dict[str, tuple[float, float, float]]
    fingerprint: SkeletonFingerprint
    project_person_id: str | None
    source: str


class AssociationAnalyzer:
    def __init__(self) -> None:
        self._project: ProjectManager | None = None

    def analyze(self, project: ProjectManager, report: QualityReport) -> AssociationReport:
        del report
        self._project = project
        issues: list[AssociationIssue] = []
        raw_frame_keys: set[tuple[str, int]] = set()
        raw = self._load_layer(project.root / "pose", "raw pose", issues, raw_frame_keys)
        synchronized = self._load_layer(project.root / "pose-sync", "synchronized pose", issues)
        associated = self._load_layer(project.root / "pose-associated", "pose-associated", issues)
        project_people = self._project_people(project.manifest.get("people"), issues)

        sync_analyzer = SynchronizationAnalyzer()
        sync_report = sync_analyzer.analyze(project)
        for sync_issue in sync_report.issues:
            issues.append(
                AssociationIssue(
                    "blocking" if sync_issue.severity == "blocking" else "warning",
                    f"synchronization mapping: {sync_issue.message}",
                    sync_issue.camera,
                    code="mapping_missing",
                )
            )

        raw_by_key: dict[tuple[str, int], list[_Detection]] = {}
        for item in raw:
            raw_by_key.setdefault((item.camera, item.frame), []).append(item)

        associated_by_key: dict[tuple[str, int, int], list[_Detection]] = {}
        for item in associated:
            if item.project_person_id is None:
                continue
            associated_by_key.setdefault(
                (item.camera, item.frame, item.raw_person_index), []
            ).append(item)

        exact_assignments: list[tuple[str, str, int, int]] = []
        candidates: list[AssociationCandidate] = []
        non_exact_groups: dict[tuple[str, int, str], list[AssociationCandidate]] = {}
        history_by_person: dict[tuple[str, str], set[int]] = {}
        for item in associated:
            if item.project_person_id:
                history_by_person.setdefault((item.camera, item.project_person_id), set()).add(
                    item.raw_person_index
                )

        for detection in synchronized:
            try:
                mapping = sync_analyzer.mapping(detection.camera, detection.frame)
            except (KeyError, ValueError) as exc:
                issues.append(
                    AssociationIssue(
                        "blocking",
                        f"no raw-frame mapping for {detection.camera} synchronized frame {detection.frame}: {exc}",
                        detection.camera,
                        detection.frame,
                        "mapping_missing",
                    )
                )
                continue
            if (detection.camera, mapping.source_frame) not in raw_frame_keys:
                issues.append(
                    AssociationIssue(
                        "blocking",
                        f"raw pose frame is missing for {detection.camera} frame {mapping.source_frame}",
                        detection.camera,
                        detection.frame,
                        "raw_layer_missing",
                    )
                )

            assignments = associated_by_key.get(
                (detection.camera, detection.frame, detection.raw_person_index), []
            )
            assigned_ids = sorted({item.project_person_id for item in assignments if item.project_person_id})
            if len(assigned_ids) > 1:
                issues.append(
                    AssociationIssue(
                        "blocking",
                        f"duplicate association assignments for {detection.camera} frame {detection.frame} person {detection.raw_person_index}",
                        detection.camera,
                        detection.frame,
                        "duplicate_assignment",
                    )
                )
            for project_person_id in assigned_ids:
                candidate = self._candidate(
                    detection,
                    project_person_id,
                    "exact",
                    1.0,
                    True,
                    "existing association layer identifies this project person at the same synchronized frame",
                )
                candidates.append(candidate)
                exact_assignments.append(
                    (project_person_id, detection.camera, detection.frame, detection.raw_person_index)
                )

            for person_id, person_record in project_people:
                if person_id in assigned_ids:
                    continue
                history = history_by_person.get((detection.camera, person_id), set())
                reference_hash = self._reference_hash(person_record)
                if reference_hash and reference_hash == detection.fingerprint.value_hash:
                    method = "spatial"
                    score = 0.95
                    explanation = "skeleton fingerprint matches the project-person reference; manual confirmation required"
                elif detection.raw_person_index in history:
                    method = "temporal"
                    score = 0.75
                    explanation = "raw person index is consistent with a previous track segment; manual confirmation required"
                else:
                    method = "spatial"
                    score = 0.5
                    explanation = "candidate is based on the available synchronized skeleton; manual confirmation required"
                candidate = self._candidate(
                    detection,
                    person_id,
                    method,
                    score,
                    False,
                    explanation,
                )
                candidates.append(candidate)
                non_exact_groups.setdefault((detection.camera, detection.frame, person_id), []).append(candidate)

        for (camera, frame, project_person_id), group in non_exact_groups.items():
            if len(group) > 1:
                issues.append(
                    AssociationIssue(
                        "warning",
                        f"multiple association candidates for {project_person_id} at {camera} frame {frame}; no candidate was applied automatically",
                        camera,
                        frame,
                        "ambiguous_candidate",
                    )
                )

        track_segments = self._track_segments(exact_assignments)
        return AssociationReport(tuple(candidates), tuple(track_segments), tuple(issues))

    def _load_layer(
        self,
        path: Path,
        layer_name: str,
        issues: list[AssociationIssue],
        present_frames: set[tuple[str, int]] | None = None,
    ) -> list[_Detection]:
        if not path.exists():
            issues.append(AssociationIssue("blocking", f"missing association input layer: {layer_name} ({path})", code="layer_missing"))
            return []
        sources: list[tuple[Path, int | None, str | None]] = []
        result_path = path / "results.json"
        if result_path.is_file():
            sources.append((result_path, None, None))
        else:
            for item in sorted(path.glob("*.json")):
                sources.append((item, self._frame_from_name(item.name), None))
            for item in sorted(path.glob("*_json/*.json")):
                camera = item.parent.name.removesuffix("_json")
                sources.append((item, self._frame_from_name(item.name), camera))
        if not sources:
            issues.append(AssociationIssue("blocking", f"missing JSON payloads in association layer: {layer_name} ({path})", code="layer_missing"))
            return []

        detections: list[_Detection] = []
        seen_frames: set[tuple[str, int]] = set()
        for source, frame_hint, camera_hint in sources:
            try:
                value = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                issues.append(AssociationIssue("blocking", f"cannot read {layer_name}: {source.name}: {exc}", code="payload_invalid"))
                continue
            if not isinstance(value, dict):
                issues.append(AssociationIssue("blocking", f"{layer_name} payload must be an object: {source.name}", code="payload_invalid"))
                continue
            if present_frames is not None:
                present_frames.update(self._payload_frame_keys(value, frame_hint, camera_hint))
            parsed = self._parse_payload(value, source, frame_hint, camera_hint, layer_name, issues)
            parsed_frames: set[tuple[str, int]] = set()
            for item in parsed:
                frame_key = (item.camera, item.frame)
                if frame_key in parsed_frames:
                    detections.append(item)
                    continue
                if frame_key in seen_frames:
                    issues.append(
                        AssociationIssue(
                            "warning",
                            f"duplicate frame in {layer_name}: {item.camera} frame {item.frame}",
                            item.camera,
                            item.frame,
                            "duplicate_frame",
                        )
                    )
                seen_frames.add(frame_key)
                parsed_frames.add(frame_key)
                detections.append(item)
        return detections

    @staticmethod
    def _payload_frame_keys(
        value: dict[str, Any],
        frame_hint: int | None,
        camera_hint: str | None,
    ) -> set[tuple[str, int]]:
        frames = value.get("frames")
        if isinstance(frames, list):
            result: set[tuple[str, int]] = set()
            for item in frames:
                if not isinstance(item, dict):
                    continue
                camera = item.get("camera", camera_hint or value.get("camera"))
                frame = item.get("frame", frame_hint)
                if isinstance(camera, str) and isinstance(frame, int) and not isinstance(frame, bool) and frame >= 0:
                    result.add((camera, frame))
            return result
        camera = camera_hint or value.get("camera")
        if isinstance(camera, str) and isinstance(frame_hint, int) and frame_hint >= 0:
            return {(camera, frame_hint)}
        return set()

    def _parse_payload(
        self,
        value: dict[str, Any],
        source: Path,
        frame_hint: int | None,
        camera_hint: str | None,
        layer_name: str,
        issues: list[AssociationIssue],
    ) -> list[_Detection]:
        frames = value.get("frames")
        if frames is not None:
            if not isinstance(frames, list):
                issues.append(AssociationIssue("blocking", f"{layer_name} frames must be a list: {source.name}", code="payload_invalid"))
                return []
            result: list[_Detection] = []
            seen_frame_keys: set[tuple[str, int]] = set()
            for frame_value in frames:
                if not isinstance(frame_value, dict):
                    issues.append(AssociationIssue("warning", f"ignored invalid frame payload in {source.name}", code="payload_invalid"))
                    continue
                frame = frame_value.get("frame", frame_hint)
                camera = frame_value.get("camera", camera_hint or value.get("camera"))
                if isinstance(camera, str) and isinstance(frame, int) and not isinstance(frame, bool):
                    frame_key = (camera, frame)
                    if frame_key in seen_frame_keys:
                        issues.append(AssociationIssue("warning", f"duplicate frame in {layer_name}: {camera} frame {frame}", camera, frame, "duplicate_frame"))
                    seen_frame_keys.add(frame_key)
                result.extend(self._parse_frame(frame_value, camera, frame, source, layer_name, issues))
            return result

        if "people" in value:
            return self._parse_frame(value, camera_hint or value.get("camera"), frame_hint, source, layer_name, issues)
        issues.append(AssociationIssue("blocking", f"{layer_name} payload has no frames or people: {source.name}", code="payload_invalid"))
        return []

    def _parse_frame(
        self,
        frame_value: dict[str, Any],
        camera_value: object,
        frame_value_number: object,
        source: Path,
        layer_name: str,
        issues: list[AssociationIssue],
    ) -> list[_Detection]:
        camera = str(camera_value) if isinstance(camera_value, str) else ""
        if not camera.strip():
            issues.append(AssociationIssue("blocking", f"{layer_name} frame has no camera: {source.name}", code="payload_invalid"))
            return []
        if not isinstance(frame_value_number, int) or isinstance(frame_value_number, bool) or frame_value_number < 0:
            issues.append(AssociationIssue("blocking", f"{layer_name} frame number is invalid: {source.name}", camera, code="payload_invalid"))
            return []
        people = frame_value.get("people")
        if not isinstance(people, list):
            issues.append(AssociationIssue("blocking", f"{layer_name} people must be a list: {source.name}", camera, frame_value_number, "payload_invalid"))
            return []
        result: list[_Detection] = []
        for ordinal, person_value in enumerate(people):
            if not isinstance(person_value, dict):
                issues.append(AssociationIssue("warning", f"ignored invalid person payload in {source.name}", camera, frame_value_number, "payload_invalid"))
                continue
            raw_index = person_value.get("raw_person_index", ordinal)
            if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
                issues.append(AssociationIssue("blocking", f"invalid raw person index in {source.name}", camera, frame_value_number, "payload_invalid"))
                continue
            points = self._points(person_value, frame_value, issues, camera, frame_value_number, source, layer_name)
            if not points:
                raw_array = person_value.get("pose_keypoints_2d")
                if isinstance(raw_array, list) and len(raw_array) % 3 == 0:
                    issues.append(AssociationIssue("warning", f"person {raw_index} has no finite keypoints in {layer_name}: {source.name}", camera, frame_value_number, "person_missing"))
                elif not person_value:
                    issues.append(AssociationIssue("warning", f"person {raw_index} is an empty missing-detection placeholder in {layer_name}: {source.name}", camera, frame_value_number, "person_missing"))
                else:
                    issues.append(AssociationIssue("blocking", f"person {raw_index} has no valid keypoints in {layer_name}: {source.name}", camera, frame_value_number, "payload_invalid"))
                continue
            fingerprint = self._fingerprint(person_value, frame_value, points)
            project_person_id = person_value.get("project_person_id")
            result.append(
                _Detection(
                    camera,
                    frame_value_number,
                    raw_index,
                    points,
                    fingerprint,
                    project_person_id if isinstance(project_person_id, str) and project_person_id.strip() else None,
                    str(source),
                )
            )
        return result

    def _points(
        self,
        person: dict[str, Any],
        frame: dict[str, Any],
        issues: list[AssociationIssue],
        camera: str,
        frame_number: int,
        source: Path,
        layer_name: str,
    ) -> dict[str, tuple[float, float, float]]:
        raw_points = person.get("keypoints")
        if isinstance(raw_points, dict):
            result: dict[str, tuple[float, float, float]] = {}
            for name, point in raw_points.items():
                if not isinstance(name, str) or not isinstance(point, dict):
                    continue
                xyz = (point.get("x"), point.get("y"), point.get("confidence", 0.0))
                if all(self._finite_number(item) for item in xyz):
                    result[name] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
            return result
        if isinstance(raw_points, list):
            result = {}
            for point in raw_points:
                if isinstance(point, dict) and isinstance(point.get("name"), str):
                    xyz = (point.get("x"), point.get("y"), point.get("confidence", 0.0))
                    if all(self._finite_number(item) for item in xyz):
                        result[point["name"]] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
            return result
        raw_array = person.get("pose_keypoints_2d")
        if isinstance(raw_array, list):
            if len(raw_array) % 3:
                issues.append(AssociationIssue("blocking", f"pose_keypoints_2d length is not divisible by three: {source.name}", camera, frame_number, "payload_invalid"))
                return {}
            names = frame.get("keypoint_names") or person.get("keypoint_names")
            result = {}
            for index in range(len(raw_array) // 3):
                name = names[index] if isinstance(names, list) and index < len(names) and isinstance(names[index], str) else f"index-{index:03d}"
                xyz = tuple(raw_array[index * 3 : index * 3 + 3])
                if all(self._finite_number(item) for item in xyz):
                    result[name] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
            return result
        return {}

    @staticmethod
    def _fingerprint(
        person: dict[str, Any],
        frame: dict[str, Any],
        points: dict[str, tuple[float, float, float]],
    ) -> SkeletonFingerprint:
        model_name = str(person.get("model_name", frame.get("model_name", "pose2d")))
        normalized = [[name, *points[name]] for name in sorted(points)]
        value = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        return SkeletonFingerprint(model_name, tuple(sorted(points)), hashlib.sha256(value.encode("utf-8")).hexdigest())

    @staticmethod
    def _candidate(
        detection: _Detection,
        project_person_id: str,
        method: str,
        score: float,
        exact: bool,
        explanation: str,
    ) -> AssociationCandidate:
        candidate_id = f"candidate-{project_person_id}-{detection.camera}-{detection.frame}-{detection.raw_person_index}"
        return AssociationCandidate(
            candidate_id,
            project_person_id,
            detection.camera,
            detection.frame,
            detection.raw_person_index,
            detection.fingerprint,
            score,
            method,  # type: ignore[arg-type]
            explanation,
            exact,
        )

    @staticmethod
    def _project_people(value: object, issues: list[AssociationIssue]) -> list[tuple[str, dict[str, Any]]]:
        if not isinstance(value, list) or not value:
            issues.append(AssociationIssue("blocking", "project manifest has no people", code="people_missing"))
            return []
        result: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("project_person_id"), str) or not item["project_person_id"].strip():
                issues.append(AssociationIssue("blocking", "project person record is invalid", code="people_invalid"))
                continue
            person_id = item["project_person_id"]
            if person_id in seen:
                issues.append(AssociationIssue("blocking", f"duplicate project person: {person_id}", code="people_duplicate"))
                continue
            seen.add(person_id)
            result.append((person_id, item))
        return result

    @staticmethod
    def _reference_hash(person: dict[str, Any]) -> str | None:
        fingerprint = person.get("fingerprint")
        if isinstance(fingerprint, dict) and isinstance(fingerprint.get("value_hash"), str):
            return fingerprint["value_hash"]
        if isinstance(fingerprint, str) and fingerprint.strip():
            return fingerprint
        return None

    @staticmethod
    def _track_segments(assignments: list[tuple[str, str, int, int]]) -> list[TrackSegment]:
        by_track: dict[tuple[str, str], set[int]] = {}
        for person_id, camera, frame, _ in assignments:
            by_track.setdefault((person_id, camera), set()).add(frame)
        result: list[TrackSegment] = []
        for (person_id, camera), frames in sorted(by_track.items()):
            ordered = sorted(frames)
            start = previous = ordered[0]
            for frame in ordered[1:]:
                if frame != previous + 1:
                    result.append(AssociationAnalyzer._segment(person_id, camera, start, previous, frames))
                    start = frame
                previous = frame
            result.append(AssociationAnalyzer._segment(person_id, camera, start, previous, frames))
        return result

    @staticmethod
    def _segment(person_id: str, camera: str, start: int, end: int, frames: set[int]) -> TrackSegment:
        safe_person = re.sub(r"[^A-Za-z0-9_.-]+", "_", person_id)
        safe_camera = re.sub(r"[^A-Za-z0-9_.-]+", "_", camera)
        return TrackSegment(f"segment-{safe_person}-{safe_camera}-{start}", person_id, camera, start, end, sum(start <= item <= end for item in frames))

    @staticmethod
    def _frame_from_name(name: str) -> int | None:
        match = re.search(r"_(\d+)\.json$", name)
        return int(match.group(1)) if match else None

    @staticmethod
    def _finite_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
