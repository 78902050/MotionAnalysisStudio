"""Append-only correction history and first-version pose backups."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.io.atomic import AtomicJsonStore
from app.io.jsonl import JsonlStore
from app.io.transactions import ProjectTransaction, TransactionRecovery
from app.pipeline.dependency_graph import invalidate_manifest
from app.project.manifest import utc_now

from .model import CorrectionOperation


def _point_index(data: dict[str, object], fallback_camera: str) -> dict[tuple[int, str, str], tuple[CorrectionTarget, tuple[float, float, float]]]:
    camera = str(data.get("camera", fallback_camera))
    model_name = str(data.get("model_name", "unknown"))
    names = data.get("keypoint_names", [])
    keypoint_names = list(names) if isinstance(names, list) else []
    result: dict[tuple[int, str, str], tuple[CorrectionTarget, tuple[float, float, float]]] = {}
    frames = data.get("frames", [])
    if not isinstance(frames, list):
        return result
    for frame_value in frames:
        if not isinstance(frame_value, dict) or not isinstance(frame_value.get("frame"), int):
            continue
        frame = frame_value["frame"]
        people = frame_value.get("people", [])
        if not isinstance(people, list):
            continue
        for ordinal, person_value in enumerate(people):
            if not isinstance(person_value, dict):
                continue
            raw_index = person_value.get("raw_person_index", ordinal)
            if not isinstance(raw_index, int):
                raw_index = ordinal
            project_person_id = str(person_value.get("project_person_id", f"raw-{raw_index}"))
            person = PersonAddress(
                project_person_id,
                person_value.get("track_segment_id") if isinstance(person_value.get("track_segment_id"), str) else None,
                raw_index,
            )
            keypoints = person_value.get("keypoints", {})
            if not isinstance(keypoints, dict):
                continue
            for keypoint_name, point_value in keypoints.items():
                if not isinstance(keypoint_name, str) or not isinstance(point_value, dict):
                    continue
                try:
                    point = (
                        float(point_value["x"]),
                        float(point_value["y"]),
                        float(point_value.get("confidence", 0.0)),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                source_index = keypoint_names.index(keypoint_name) if keypoint_name in keypoint_names else None
                target = CorrectionTarget(
                    FrameAddress(camera, "pose2d", frame),
                    person,
                    KeypointAddress(model_name, keypoint_name, source_index),
                )
                result[(frame, project_person_id, keypoint_name)] = (target, point)
    return result


class CorrectionHistory:
    def __init__(self, root: Path) -> None:
        base = root.root if hasattr(root, "manifest") and hasattr(root, "root") else root
        self.root = Path(base)
        self.path = self.root / "corrections" / "history.jsonl"
        self.store = JsonlStore(self.path)

    def append(self, operation: CorrectionOperation) -> None:
        self.store.append(operation.to_dict())

    def serialized_with(self, operations: list[CorrectionOperation]) -> bytes:
        records, errors = self.store.read()
        if errors:
            raise ValueError("invalid correction history: " + "; ".join(errors))
        records.extend(operation.to_dict() for operation in operations)
        payload = "".join(
            json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            + "\n"
            for record in records
        )
        return payload.encode("utf-8")

    def operations(self, session_id: str | None = None) -> list[CorrectionOperation]:
        records, errors = self.store.read()
        if errors:
            raise ValueError("invalid correction history: " + "; ".join(errors))
        operations = [CorrectionOperation.from_dict(record) for record in records]
        if session_id is None:
            return operations
        return [operation for operation in operations if operation.session_id == session_id]

    def backup_path(self, json_path: Path) -> Path:
        json_path = Path(json_path)
        camera_directory = json_path.parent.name
        if not camera_directory.endswith("_json"):
            camera_directory = f"{json_path.stem}_json"
        return (
            self.root
            / "corrections"
            / "backups"
            / "pose"
            / camera_directory
            / json_path.name
        )

    def backup_once(self, json_path: Path) -> bool:
        return AtomicJsonStore.backup_once(Path(json_path), self.backup_path(Path(json_path)))

    def commit_pose_change(
        self,
        json_path: Path,
        data: dict[str, object],
        operations: list[CorrectionOperation],
        *,
        create_backup: bool,
    ) -> None:
        root = self.root.resolve()
        pose_path = Path(json_path).resolve()
        try:
            pose_relative = pose_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("pose JSON must be located inside the project root") from exc

        transaction = ProjectTransaction(root)
        transaction.prepare_json(pose_relative, data, allow_nan=True)
        transaction.prepare_bytes(
            self.path.resolve().relative_to(root),
            self.serialized_with(operations),
        )
        backup_path = self.backup_path(pose_path).resolve()
        if create_backup and not backup_path.exists():
            transaction.prepare_bytes(backup_path.relative_to(root), pose_path.read_bytes())

        manifest_path = root / "manifest.json"
        if manifest_path.is_file() and operations:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("project manifest must contain an object")
            operation_ids = [operation.operation_id for operation in operations]
            manual_edits = manifest.setdefault("manual_pose_edits", [])
            if not isinstance(manual_edits, list):
                raise ValueError("manual_pose_edits must be a list")
            manual_edits.extend(operation_ids)
            invalidate_manifest(
                manifest,
                "personAssociation",
                "confirmed 2D correction",
                operation_ids,
            )
            manifest["updated_at"] = utc_now()
            transaction.prepare_json("manifest.json", manifest)

        try:
            transaction.commit()
        except BaseException:
            TransactionRecovery(root).recover_all()
            raise

    def restore_file(self, json_path: Path, reason: str) -> int:
        json_path = Path(json_path)
        backup = self.backup_path(json_path)
        if not backup.is_file():
            raise FileNotFoundError(f"pose backup not found: {backup}")
        current_value = json.loads(json_path.read_text(encoding="utf-8"))
        backup_value = json.loads(backup.read_text(encoding="utf-8"))
        if not isinstance(current_value, dict) or not isinstance(backup_value, dict):
            raise ValueError("pose JSON must contain an object")

        current = _point_index(current_value, json_path.stem)
        original = _point_index(backup_value, json_path.stem)
        operations: list[CorrectionOperation] = []
        now = datetime.now(timezone.utc).isoformat()
        session_id = f"restore-{uuid4().hex}"
        for key in sorted(set(current) & set(original)):
            target, before = current[key]
            _, after = original[key]
            if before == after:
                continue
            operations.append(
                CorrectionOperation(
                    operation_id=f"op-{uuid4().hex}",
                    session_id=session_id,
                    target=target,
                    before=before,
                    after=after,
                    note=reason,
                    created_at=now,
                    source="restore",
                )
            )

        for key in sorted(set(original) - set(current)):
            target, after = original[key]
            operations.append(
                CorrectionOperation(
                    operation_id=f"op-{uuid4().hex}",
                    session_id=session_id,
                    target=target,
                    before=after,
                    after=after,
                    note=reason,
                    created_at=now,
                    source="restore",
                    change_kind="added",
                )
            )
        for key in sorted(set(current) - set(original)):
            target, before = current[key]
            operations.append(
                CorrectionOperation(
                    operation_id=f"op-{uuid4().hex}",
                    session_id=session_id,
                    target=target,
                    before=before,
                    after=before,
                    note=reason,
                    created_at=now,
                    source="restore",
                    change_kind="removed",
                )
            )

        if current_value == backup_value:
            return 0
        self.commit_pose_change(json_path, backup_value, operations, create_backup=False)
        return len(operations)
