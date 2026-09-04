"""Semantic, in-memory editing of one Pose2Sim 2D pose JSON file."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.correction.change_set import ChangeSet, PointValue
from app.correction.history import CorrectionHistory
from app.correction.model import CorrectionOperation, CorrectionSource
from app.domain.addresses import CorrectionTarget


class PoseDocument:
    def __init__(self, path: Path, project_root: Path | None = None) -> None:
        self.path = Path(path)
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("pose JSON must contain an object")
        self.data: dict[str, object] = value
        self.project_root = Path(project_root) if project_root is not None else self.path.parent.parent
        self._saved_data = copy.deepcopy(self.data)
        self._pending_operations: list[CorrectionOperation] = []

    def _locate_point_in(
        self, data: dict[str, object], target: CorrectionTarget
    ) -> dict[str, object]:
        if target.address.camera != str(data.get("camera", target.address.camera)):
            raise ValueError(f"pose JSON camera does not match target camera: {target.address.camera}")
        frames = data.get("frames", [])
        if not isinstance(frames, list):
            raise ValueError("pose JSON frames must be a list")
        frame_value = next(
            (item for item in frames if isinstance(item, dict) and item.get("frame") == target.address.frame),
            None,
        )
        if not isinstance(frame_value, dict):
            raise KeyError(f"frame not found: {target.address.frame}")
        people = frame_value.get("people", [])
        if not isinstance(people, list):
            raise ValueError("pose JSON people must be a list")

        semantic_people = [item for item in people if isinstance(item, dict) and "project_person_id" in item]
        person_value = next(
            (
                item
                for item in semantic_people
                if item.get("project_person_id") == target.person.project_person_id
            ),
            None,
        )
        if person_value is None and not semantic_people:
            person_value = next(
                (
                    item
                    for ordinal, item in enumerate(people)
                    if isinstance(item, dict)
                    and item.get("raw_person_index", ordinal) == target.person.raw_person_index
                ),
                None,
            )
        if not isinstance(person_value, dict):
            raise KeyError(f"person not found: {target.person.project_person_id}")
        keypoints = person_value.get("keypoints", {})
        if not isinstance(keypoints, dict) or target.keypoint.keypoint_name not in keypoints:
            raise KeyError(f"keypoint not found by name: {target.keypoint.keypoint_name}")
        point = keypoints[target.keypoint.keypoint_name]
        if not isinstance(point, dict):
            raise ValueError("keypoint payload must be an object")
        return point

    def _locate_point(self, target: CorrectionTarget) -> dict[str, object]:
        return self._locate_point_in(self.data, target)

    def _value_in(
        self, data: dict[str, object], target: CorrectionTarget
    ) -> PointValue:
        point = self._locate_point_in(data, target)
        try:
            return (
                float(point["x"]),
                float(point["y"]),
                float(point.get("confidence", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("keypoint payload has invalid coordinates") from exc

    def value_at(self, target: CorrectionTarget) -> tuple[float, float, float]:
        return self._value_in(self.data, target)

    def set_point_value(
        self,
        target: CorrectionTarget,
        value: tuple[float, float, float],
        *,
        session_id: str,
        note: str = "",
        source: CorrectionSource = "manual",
        record: bool = True,
    ) -> CorrectionOperation | None:
        point = self._locate_point(target)
        before = self.value_at(target)
        after = tuple(float(item) for item in value)
        point["x"], point["y"], point["confidence"] = after
        if not record:
            return None
        operation = CorrectionOperation(
            operation_id=f"op-{uuid4().hex}",
            session_id=session_id,
            target=target,
            before=before,
            after=after,
            note=note,
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source,
        )
        self._pending_operations.append(operation)
        return operation

    @property
    def pending_operations(self) -> tuple[CorrectionOperation, ...]:
        return tuple(self._pending_operations)

    def remove_pending(self, operation_ids: set[str]) -> None:
        self._pending_operations = [
            operation for operation in self._pending_operations if operation.operation_id not in operation_ids
        ]

    def discard_unsaved(self) -> None:
        self.data = copy.deepcopy(self._saved_data)
        self._pending_operations.clear()

    def change_set(self) -> ChangeSet:
        targets = tuple(dict.fromkeys(operation.target for operation in self._pending_operations))
        baseline = {target: self._value_in(self._saved_data, target) for target in targets}
        current = {target: self._value_in(self.data, target) for target in targets}
        return ChangeSet.between(baseline, current)

    def has_net_changes(self) -> bool:
        return bool(self.change_set())

    def save(self, note: str = "", session_id: str = "") -> tuple[int, list[str]]:
        changes = self.change_set()
        if not changes:
            self._pending_operations.clear()
            return 0, []
        history = CorrectionHistory(self.project_root)
        operations = [
            CorrectionOperation(
                operation_id=f"op-{uuid4().hex}",
                session_id=session_id or self._pending_operations[-1].session_id,
                target=change.target,
                before=change.before,
                after=change.after,
                note=note,
                created_at=datetime.now(timezone.utc).isoformat(),
                source="manual",
            )
            for change in changes.changes
        ]
        history.commit_pose_change(self.path, self.data, operations, create_backup=True)
        self._pending_operations.clear()
        self._saved_data = copy.deepcopy(self.data)
        return len(operations), [operation.operation_id for operation in operations]
