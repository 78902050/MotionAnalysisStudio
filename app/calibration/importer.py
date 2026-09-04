"""Import calibration JSON without modifying the external source file."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.stages import StageGraph
from app.project.manager import ProjectManager

from .model import CalibrationFingerprint


@dataclass(frozen=True)
class ImportResult:
    changed: bool
    active_path: Path
    fingerprint: str
    invalidated_stages: tuple[str, ...]


def _camera_ids(value: dict[str, Any], source: Path) -> tuple[str, ...]:
    cameras = value.get("cameras")
    if not isinstance(cameras, list):
        raise ValueError(f"calibration JSON has no cameras list: {source}")
    result: list[str] = []
    for camera in cameras:
        if not isinstance(camera, dict) or not isinstance(camera.get("camera_id"), str):
            raise ValueError(f"calibration camera has no camera_id: {source}")
        camera_id = camera["camera_id"].strip()
        if not camera_id or camera_id in result:
            raise ValueError(f"calibration camera IDs must be non-empty and unique: {source}")
        result.append(camera_id)
    if not result:
        raise ValueError(f"calibration JSON has no cameras: {source}")
    return tuple(result)


class CalibrationImporter:
    def inspect(self, path: Path) -> CalibrationFingerprint:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"calibration source not found: {path}")
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid calibration JSON: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"calibration JSON root must be an object: {path}")
        stat = path.stat()
        return CalibrationFingerprint(
            path=path,
            fingerprint=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            camera_ids=_camera_ids(value, path),
        )

    def import_file(self, project: ProjectManager, path: Path) -> ImportResult:
        path = Path(path)
        fingerprint = self.inspect(path)
        active_path = project.root / "calibration" / "source" / path.name
        existing = project.manifest.get("calibration")
        same_content = (
            isinstance(existing, dict)
            and existing.get("fingerprint") == fingerprint.fingerprint
            and active_path.is_file()
        )
        if same_content:
            return ImportResult(False, active_path, fingerprint.fingerprint, ())

        raw = path.read_bytes()
        active_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{active_path.name}.", suffix=".tmp", dir=active_path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, active_path)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

        affected = tuple(StageGraph().invalidate_from("calibration", "calibration import"))
        stages = project.manifest.setdefault("stages", {})
        for stage in affected:
            record = stages.setdefault(stage, {"status": "not_started", "generation": 0})
            record["status"] = "pending" if stage == "calibration" else "stale"
            record["generation"] = int(record.get("generation", 0)) + 1
            record["invalidated_reason"] = "calibration import"
        project.manifest["calibration"] = {
            "active_path": str(active_path.relative_to(project.root)),
            "source_path": str(path),
            "fingerprint": fingerprint.fingerprint,
            "size": fingerprint.size,
            "modified_at": fingerprint.modified_at,
            "camera_ids": list(fingerprint.camera_ids),
        }
        project.manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        project.save_manifest()
        return ImportResult(True, active_path, fingerprint.fingerprint, affected)
