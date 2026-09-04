"""Atomically materialize confirmed association constraints."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Sequence

from app.domain.stages import StageGraph
from app.io.atomic import AtomicJsonStore
from app.project.manager import ProjectManager
from app.project.manifest import utc_now

from .model import AssociationOverride, MaterializeResult, TrackSegment


class AssociationMaterializer:
    def materialize(
        self,
        project: ProjectManager,
        constraints: Sequence[AssociationOverride],
    ) -> MaterializeResult:
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

        try:
            AtomicJsonStore.backup_once(output_path, backup_path)
            constraint_by_target = {
                (item.camera, item.synchronized_frame, item.raw_person_index): item
                for item in constraints
            }
            for frame_value in payload["frames"]:
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
                    # Unconfirmed automatic IDs are not materialized. The detection remains
                    # in the output so a later reviewer can confirm it explicitly.
                    person_value.pop("project_person_id", None)
                    person_value.pop("track_segment_id", None)
                    override = constraint_by_target.get((camera, frame, raw_index))
                    if override is not None:
                        person_value["project_person_id"] = override.project_person_id

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
                for person_value in people:
                    if not isinstance(person_value, dict):
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
            AtomicJsonStore.replace(output_path, payload)
            if constraints:
                self._invalidate_downstream(project, [item.override_id for item in constraints])
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
    def _invalidate_downstream(project: ProjectManager, operation_ids: list[str]) -> None:
        affected = StageGraph().invalidate_from("triangulation", "human association confirmation", operation_ids[0] if operation_ids else None)
        stages = project.manifest.setdefault("stages", {})
        for stage in affected:
            record = stages.setdefault(stage, {"status": "not_started", "generation": 0})
            status = record.get("status")
            record["status"] = "stale" if status in {"completed", "running", "failed", "cancelled"} else "pending"
            record["generation"] = int(record.get("generation", 0)) + 1
            record["invalidated_by"] = list(operation_ids)
            record["invalidation_reason"] = "human association confirmation"
        project.manifest["updated_at"] = utc_now()
        project.save_manifest()

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
