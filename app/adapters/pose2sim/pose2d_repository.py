"""Read and minimally update Pose2Sim/OpenPose per-frame JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.pose2d import FramePose, PersonPose, PoseKeypoint
from app.io.atomic import AtomicJsonStore


class Pose2DFrameDocument:
    def __init__(
        self,
        path: Path,
        camera: str,
        frame: int,
        keypoint_names: tuple[str, ...],
        data: dict[str, object],
    ) -> None:
        self.path = Path(path)
        self.camera = camera
        self.frame = frame
        self.keypoint_names = keypoint_names
        self.data = data
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
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("pose keypoint value must contain x, y, and confidence")
        normalized: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise ValueError("pose keypoint values must be numeric")
            normalized.append(float(item))
        values = self._keypoint_values(person_index)
        start = keypoint_index * 3
        before = tuple(float(item) for item in values[start : start + 3])
        values[start : start + 3] = normalized
        return before  # type: ignore[return-value]

    def save(self) -> None:
        AtomicJsonStore.replace(self.path, self.data, allow_nan=True)


class Pose2DRepository:
    def __init__(self, pose_root: Path, keypoint_names: tuple[str, ...]) -> None:
        self.pose_root = Path(pose_root).resolve()
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
        return Pose2DFrameDocument(candidate, camera, frame, self.keypoint_names, data)

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
