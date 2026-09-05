"""Atomically materialize confirmed association constraints."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Sequence

from app.io.atomic import AtomicJsonStore
from app.io.transactions import ProjectTransaction
from app.pipeline.dependency_graph import invalidate_manifest
from app.project.manager import ProjectManager
from app.project.manifest import utc_now
from app.tasks.base import CancellationToken

from .model import AssociationOverride, MaterializeResult, TrackSegment


class AssociationMaterializer:
    def materialize(
        self,
        project: ProjectManager,
        constraints: Sequence[AssociationOverride],
        *,
        token: CancellationToken | None = None,
    ) -> MaterializeResult:
        if token is not None:
            token.raise_if_cancelled()
        output_path = project.root / "pose-associated" / "results.json"
        backup_path = project.root / "corrections" / "backups" / "association" / "results.json"
        if not output_path.is_file():
            return MaterializeResult(False, output_path, None, error=f"association output not found: {output_path}")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return MaterializeResult(False, output_path, None, error=f"association output is unreadable: {exc}")
        if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
            return MaterializeResult(False, output_path, None, error="association output frames must be a list")

        original_payload = copy.deepcopy(payload)
        try:
            constraint_by_target = {
                (item.camera, item.synchronized_frame, item.raw_person_index): item
                for item in constraints
            }
            found_targets: set[tuple[str, int, int]] = set()
            for frame_value in payload["frames"]:
                if token is not None:
                    token.raise_if_cancelled()
                if not isinstance(frame_value, dict):
                    continue
                camera = frame_value.get("camera")
                frame = frame_value.get("frame")
                if not isinstance(camera, str) or not isinstance(frame, int):
                    continue
                people = frame_value.get("people")
                if not isinstance(people, list):
                    continue
                for ordinal, person_value in enumerate(people):
                    if not isinstance(person_value, dict):
                        continue
                    raw_index = person_value.get("raw_person_index", ordinal)
                    if not isinstance(raw_index, int):
                        raw_index = ordinal
                    target = (camera, frame, raw_index)
                    override = constraint_by_target.get(target)
                    if override is not None:
                        found_targets.add(target)
                        person_value["project_person_id"] = override.project_person_id

            missing_targets = set(constraint_by_target) - found_targets
            if missing_targets:
                missing = ", ".join(f"{camera}/{frame}/{person}" for camera, frame, person in sorted(missing_targets))
                return MaterializeResult(False, output_path, backup_path if backup_path.is_file() else None, error=f"confirmed association targets are missing: {missing}")

            assignments = self._assignments(payload["frames"])
            segments = self._segments(assignments)
            for frame_value in payload["frames"]:
                if not isinstance(frame_value, dict):
                    continue
                camera = frame_value.get("camera")
                frame = frame_value.get("frame")
                people = frame_value.get("people")
                if not isinstance(camera, str) or not isinstance(frame, int) or not isinstance(people, list):
                    continue
                for ordinal, person_value in enumerate(people):
                    if not isinstance(person_value, dict):
                        continue
                    raw_index = person_value.get("raw_person_index", ordinal)
                    if (camera, frame, raw_index) not in found_targets:
                        continue
                    person_id = person_value.get("project_person_id")
                    if not isinstance(person_id, str):
                        continue
                    segment = next(
                        (
                            item
                            for item in segments
                            if item.project_person_id == person_id
                            and item.camera == camera
                            and item.start_frame <= frame <= item.end_frame
                        ),
                        None,
                    )
                    if segment is not None:
                        person_value["track_segment_id"] = segment.segment_id
            if payload == original_payload:
                return MaterializeResult(
                    True,
                    output_path,
                    backup_path if backup_path.is_file() else None,
                    tuple(segments),
                )
            if token is not None:
                token.raise_if_cancelled()
            AtomicJsonStore.backup_once(output_path, backup_path)
            manifest = copy.deepcopy(project.manifest)
            if constraints:
                self._invalidate_downstream(manifest, [item.override_id for item in constraints])
            transaction = ProjectTransaction(project.root)
            transaction.prepare_json(output_path.relative_to(project.root), payload)
            transaction.prepare_json("manifest.json", manifest)
            if token is not None:
                token.raise_if_cancelled()
            transaction.commit()
            project.manifest = manifest
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return MaterializeResult(False, output_path, backup_path if backup_path.is_file() else None, error=str(exc))
        return MaterializeResult(True, output_path, backup_path, tuple(segments))

    def restore(self, project: ProjectManager) -> MaterializeResult:
        output_path = project.root / "pose-associated" / "results.json"
        backup_path = project.root / "corrections" / "backups" / "association" / "results.json"
        if not backup_path.is_file():
            return MaterializeResult(False, output_path, None, error=f"association backup not found: {backup_path}")
        try:
            payload = json.loads(backup_path.read_text(encoding="utf-8"))
            AtomicJsonStore.replace(output_path, payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return MaterializeResult(False, output_path, backup_path, error=f"cannot restore association output: {exc}")
        return MaterializeResult(True, output_path, backup_path, restored=True)

    @staticmethod
    def _invalidate_downstream(manifest: dict[str, object], operation_ids: list[str]) -> None:
        invalidate_manifest(
            manifest,
            "triangulation",
            "human association confirmation",
            operation_ids,
        )
        manifest["updated_at"] = utc_now()

    @staticmethod
    def _assignments(frames: list[object]) -> list[tuple[str, str, int]]:
        assignments: list[tuple[str, str, int]] = []
        for frame_value in frames:
            if not isinstance(frame_value, dict):
                continue
            camera = frame_value.get("camera")
            frame = frame_value.get("frame")
            people = frame_value.get("people")
            if not isinstance(camera, str) or not isinstance(frame, int) or not isinstance(people, list):
                continue
            for person_value in people:
                if isinstance(person_value, dict) and isinstance(person_value.get("project_person_id"), str):
                    assignments.append((person_value["project_person_id"], camera, frame))
        return assignments

    @staticmethod
    def _segments(assignments: list[tuple[str, str, int]]) -> list[TrackSegment]:
        by_track: dict[tuple[str, str], set[int]] = {}
        for project_person_id, camera, frame in assignments:
            by_track.setdefault((project_person_id, camera), set()).add(frame)
        result: list[TrackSegment] = []
        for (person_id, camera), frames in sorted(by_track.items()):
            ordered = sorted(frames)
            start = previous = ordered[0]
            for frame in ordered[1:]:
                if frame != previous + 1:
                    result.append(AssociationMaterializer._segment(person_id, camera, start, previous, frames))
                    start = frame
                previous = frame
            result.append(AssociationMaterializer._segment(person_id, camera, start, previous, frames))
        return result

    @staticmethod
    def _segment(person_id: str, camera: str, start: int, end: int, frames: set[int]) -> TrackSegment:
        safe_person = re.sub(r"[^A-Za-z0-9_.-]+", "_", person_id)
        safe_camera = re.sub(r"[^A-Za-z0-9_.-]+", "_", camera)
        return TrackSegment(
            f"segment-{safe_person}-{safe_camera}-{start}",
            person_id,
            camera,
            start,
            end,
            sum(start <= item <= end for item in frames),
        )
