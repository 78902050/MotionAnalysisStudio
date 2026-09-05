"""Read and minimally update Pose2Sim/OpenPose per-frame JSON files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.correction.history import CorrectionHistory
from app.correction.model import CorrectionOperation
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.domain.pose2d import FramePose, PersonPose, PoseKeypoint


class Pose2DFrameDocument:
    def __init__(
        self,
        path: Path,
        camera: str,
        frame: int,
        keypoint_names: tuple[str, ...],
        data: dict[str, object],
        project_root: Path,
        model_name: str,
    ) -> None:
        self.path = Path(path)
        self.camera = camera
        self.frame = frame
        self.keypoint_names = keypoint_names
        self.data = data
        self.project_root = Path(project_root)
        self.model_name = model_name
        self._baseline: dict[CorrectionTarget, tuple[float, float, float]] = {}
        self._pending_operations: list[CorrectionOperation] = []
        self._validate()

    def _people(self) -> list[dict[str, object]]:
        people = self.data.get("people")
        if not isinstance(people, list) or any(not isinstance(person, dict) for person in people):
            raise ValueError(f"Pose2Sim people must be an array of objects: {self.path}")
        return people

    def _keypoint_values(self, person_index: int) -> list[object]:
        people = self._people()
        if not isinstance(person_index, int) or isinstance(person_index, bool) or not 0 <= person_index < len(people):
            raise IndexError(f"Pose2Sim person index out of range: {person_index}")
        values = people[person_index].get("pose_keypoints_2d")
        if not isinstance(values, list) or len(values) % 3:
            raise ValueError(f"Pose2Sim pose_keypoints_2d length is not divisible by three: {self.path}")
        if len(values) // 3 != len(self.keypoint_names):
            raise ValueError(
                f"Pose2Sim keypoint name count {len(self.keypoint_names)} does not match "
                f"array count {len(values) // 3}: {self.path}"
            )
        return values

    def _validate(self) -> None:
        people = self._people()
        for index in range(len(people)):
            values = self._keypoint_values(index)
            for value in values:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"Pose2Sim keypoint values must be numeric: {self.path}")

    def frame_pose(self) -> FramePose:
        result: list[PersonPose] = []
        for person_index, person in enumerate(self._people()):
            values = self._keypoint_values(person_index)
            points = tuple(
                PoseKeypoint(
                    name=name,
                    x=float(values[index * 3]),
                    y=float(values[index * 3 + 1]),
                    confidence=float(values[index * 3 + 2]),
                )
                for index, name in enumerate(self.keypoint_names)
            )
            project_person_id = person.get("project_person_id")
            track_segment_id = person.get("track_segment_id")
            result.append(
                PersonPose(
                    raw_person_index=person_index,
                    project_person_id=project_person_id if isinstance(project_person_id, str) else None,
                    track_segment_id=track_segment_id if isinstance(track_segment_id, str) else None,
                    keypoints=points,
                )
            )
        return FramePose(self.camera, self.frame, tuple(result), self.path)

    def set_point(
        self,
        person_index: int,
        keypoint_name: str,
        value: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        try:
            keypoint_index = self.keypoint_names.index(keypoint_name)
        except ValueError as exc:
            raise KeyError(f"unknown keypoint name: {keypoint_name}") from exc
        person = self._people()[person_index]
        project_person_id = person.get("project_person_id")
        track_segment_id = person.get("track_segment_id")
        target = CorrectionTarget(
            FrameAddress(self.camera, "pose2d", self.frame),
            PersonAddress(
                project_person_id if isinstance(project_person_id, str) else f"raw-{person_index}",
                track_segment_id if isinstance(track_segment_id, str) else None,
                person_index,
            ),
            KeypointAddress(self.model_name, keypoint_name, keypoint_index),
        )
        return self._set_point_for_target(person_index, target, value)

    def _set_point_for_target(
        self,
        person_index: int,
        target: CorrectionTarget,
        value: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("pose keypoint value must contain x, y, and confidence")
        normalized: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise ValueError("pose keypoint values must be numeric")
            normalized.append(float(item))
        keypoint_name = target.keypoint.keypoint_name
        try:
            keypoint_index = self.keypoint_names.index(keypoint_name)
        except ValueError as exc:
            raise KeyError(f"unknown keypoint name: {keypoint_name}") from exc
        values = self._keypoint_values(person_index)
        start = keypoint_index * 3
        before = tuple(float(item) for item in values[start : start + 3])
        self._baseline.setdefault(target, before)  # first value is the save baseline
        values[start : start + 3] = normalized
        return before  # type: ignore[return-value]

    def value_at(self, target: CorrectionTarget) -> tuple[float, float, float]:
        self._validate_target(target)
        person_index = self._person_ordinal(target)
        keypoint_index = self.keypoint_names.index(target.keypoint.keypoint_name)
        values = self._keypoint_values(person_index)
        start = keypoint_index * 3
        return tuple(float(item) for item in values[start : start + 3])  # type: ignore[return-value]

    def set_point_value(
        self,
        target: CorrectionTarget,
        value: tuple[float, float, float],
        *,
        session_id: str,
        note: str = "",
        source: str = "manual",
        record: bool = True,
    ) -> CorrectionOperation | None:
        self._validate_target(target)
        person_index = self._person_ordinal(target)
        before = self._set_point_for_target(person_index, target, value)
        if not record:
            return None
        operation = CorrectionOperation(
            operation_id=f"op-{uuid4().hex}",
            session_id=session_id,
            target=target,
            before=before,
            after=tuple(float(item) for item in value),  # type: ignore[arg-type]
            note=note,
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source,  # type: ignore[arg-type]
        )
        self._pending_operations.append(operation)
        return operation

    @property
    def pending_operations(self) -> tuple[CorrectionOperation, ...]:
        return tuple(self._pending_operations)

    def remove_pending(self, operation_ids: set[str]) -> None:
        self._pending_operations = [
            operation
            for operation in self._pending_operations
            if operation.operation_id not in operation_ids
        ]

    def has_net_changes(self) -> bool:
        return any(self.value_at(target) != before for target, before in self._baseline.items())

    def discard_unsaved(self) -> None:
        for target, before in tuple(self._baseline.items()):
            person_index = self._person_ordinal(target)
            self._set_point_for_target(person_index, target, before)
        self._baseline.clear()
        self._pending_operations.clear()

    def _validate_target(self, target: CorrectionTarget) -> None:
        if target.address.camera != self.camera or target.address.frame != self.frame:
            raise KeyError(
                f"Pose2Sim frame does not match target: {target.address.camera} {target.address.frame}"
            )
        if target.keypoint.keypoint_name not in self.keypoint_names:
            raise KeyError(f"unknown keypoint name: {target.keypoint.keypoint_name}")

    def _person_ordinal(self, target: CorrectionTarget) -> int:
        people = self._people()
        semantic = [
            index
            for index, person in enumerate(people)
            if person.get("project_person_id") == target.person.project_person_id
        ]
        if len(semantic) == 1:
            return semantic[0]
        if len(semantic) > 1:
            raise KeyError(f"multiple Pose2Sim people match: {target.person.project_person_id}")
        raw_index = target.person.raw_person_index
        if raw_index is None:
            raise KeyError(f"Pose2Sim person has no raw index: {target.person.project_person_id}")
        matching = [
            index
            for index, person in enumerate(people)
            if person.get("raw_person_index", index) == raw_index
        ]
        if len(matching) != 1:
            raise KeyError(f"Pose2Sim person index is not unique: {raw_index}")
        return matching[0]

    def save(self, note: str = "", session_id: str = "") -> tuple[int, list[str]]:
        now = datetime.now(timezone.utc).isoformat()
        effective_session = session_id or f"session-{uuid4().hex}"
        operations: list[CorrectionOperation] = []
        for target, before in self._baseline.items():
            values = self._keypoint_values(self._person_ordinal(target))
            index = target.keypoint.source_index
            if index is None:
                raise ValueError(f"keypoint has no source index: {target.keypoint.keypoint_name}")
            start = index * 3
            after = tuple(float(item) for item in values[start : start + 3])
            if before == after:
                continue
            operations.append(
                CorrectionOperation(
                    operation_id=f"op-{uuid4().hex}",
                    session_id=effective_session,
                    target=target,
                    before=before,
                    after=after,  # type: ignore[arg-type]
                    note=note,
                    created_at=now,
                    source="manual",
                )
            )
        if not operations:
            self._baseline.clear()
            return 0, []
        history = CorrectionHistory(self.project_root)
        history.commit_pose_change(self.path, self.data, operations, create_backup=True)
        self._baseline.clear()
        self._pending_operations.clear()
        return len(operations), [operation.operation_id for operation in operations]


class Pose2DRepository:
    def __init__(
        self,
        pose_root: Path,
        keypoint_names: tuple[str, ...],
        *,
        project_root: Path | None = None,
        model_name: str = "unknown",
    ) -> None:
        self.pose_root = Path(pose_root).resolve()
        self.project_root = (
            Path(project_root).resolve() if project_root is not None else self.pose_root.parent
        )
        self.model_name = model_name
        self.keypoint_names = tuple(keypoint_names)
        if not self.keypoint_names or any(not isinstance(name, str) or not name.strip() for name in self.keypoint_names):
            raise ValueError("keypoint names must contain non-empty strings")
        if len(set(self.keypoint_names)) != len(self.keypoint_names):
            raise ValueError("keypoint names must be unique")

    def load_frame(self, camera: str, frame: int) -> Pose2DFrameDocument:
        if not isinstance(camera, str) or not camera.strip() or any(token in camera for token in ("/", "\\")):
            raise ValueError("camera must be a simple non-empty name")
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
            raise ValueError("frame must be a non-negative integer")
        directory = self.pose_root / f"{camera}_json"
        candidate = directory / f"{camera}_{frame:06d}.json"
        if not candidate.is_file():
            candidate = self._find_frame(directory, camera, frame)
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Pose2Sim JSON: {candidate}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Pose2Sim JSON root must be an object: {candidate}")
        return Pose2DFrameDocument(
            candidate,
            camera,
            frame,
            self.keypoint_names,
            data,
            self.project_root,
            self.model_name,
        )

    @staticmethod
    def _find_frame(directory: Path, camera: str, frame: int) -> Path:
        if not directory.is_dir():
            raise FileNotFoundError(f"Pose2Sim camera directory not found: {directory}")
        prefix = f"{camera}_"
        for path in directory.glob(f"{camera}_*.json"):
            suffix = path.stem[len(prefix) :]
            if suffix.isdigit() and int(suffix) == frame:
                return path
        raise FileNotFoundError(f"Pose2Sim frame not found: camera={camera}, frame={frame}")
