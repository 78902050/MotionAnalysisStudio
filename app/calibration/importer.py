"""Preview and transactionally activate validated calibration files."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.caliscope.calibration_repository import CaliscopeCalibrationRepository
from app.domain.calibration import CalibrationSet
from app.domain.stages import StageGraph
from app.io.transactions import ProjectTransaction
from app.project.manager import ProjectManager

from .model import CalibrationFingerprint, CalibrationIssue, CalibrationPreview


@dataclass(frozen=True)
class ImportResult:
    changed: bool
    active_path: Path
    fingerprint: str
    invalidated_stages: tuple[str, ...]


def _canonical(calibration: CalibrationSet) -> dict[str, object]:
    return {
        "cameras": {
            camera.camera: {
                "image_size": list(camera.image_size),
                "matrix": [list(row) for row in camera.matrix],
                "distortions": list(camera.distortions),
                "rotation": list(camera.rotation),
                "translation": list(camera.translation),
                "reprojection_error": camera.reprojection_error,
            }
            for camera in sorted(calibration.cameras, key=lambda item: item.camera)
        }
    }


def _semantic_fingerprint(calibration: CalibrationSet) -> str:
    payload = json.dumps(
        _canonical(calibration),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _differences(before: CalibrationSet | None, after: CalibrationSet) -> tuple[str, ...]:
    if before is None:
        return tuple(f"新增相机 {camera.camera}" for camera in after.cameras)
    old = _canonical(before)["cameras"]
    new = _canonical(after)["cameras"]
    assert isinstance(old, dict) and isinstance(new, dict)
    result: list[str] = []
    for camera in sorted(set(old) - set(new)):
        result.append(f"移除相机 {camera}")
    for camera in sorted(set(new) - set(old)):
        result.append(f"新增相机 {camera}")
    for camera in sorted(set(old) & set(new)):
        old_fields = old[camera]
        new_fields = new[camera]
        assert isinstance(old_fields, dict) and isinstance(new_fields, dict)
        for field in old_fields:
            if old_fields[field] != new_fields[field]:
                result.append(
                    f"相机 {camera} 的 {field}: "
                    f"{old_fields[field]!r} → {new_fields[field]!r}"
                )
    return tuple(result)


class CalibrationImporter:
    def __init__(self) -> None:
        self.repository = CaliscopeCalibrationRepository()

    def inspect(self, path: Path) -> CalibrationFingerprint:
        path = Path(path)
        calibration = self.repository.load(path)
        stat = path.stat()
        return CalibrationFingerprint(
            path=path,
            fingerprint=_semantic_fingerprint(calibration),
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            camera_ids=tuple(camera.camera for camera in calibration.cameras),
        )

    def preview(self, project: ProjectManager, path: Path) -> CalibrationPreview:
        path = Path(path)
        calibration = self.repository.load(path)
        fingerprint = _semantic_fingerprint(calibration)
        differences = _differences(self._active_calibration(project), calibration)
        expected = {
            str(item["camera_id"])
            for item in project.manifest.get("cameras", [])
            if isinstance(item, dict) and isinstance(item.get("camera_id"), str)
        }
        actual = {camera.camera for camera in calibration.cameras}
        issues: list[CalibrationIssue] = []
        if expected and expected != actual:
            missing = ", ".join(sorted(expected - actual)) or "无"
            extra = ", ".join(sorted(actual - expected)) or "无"
            issues.append(
                CalibrationIssue(
                    "blocking",
                    f"标定相机集合与项目不一致；缺少：{missing}；多出：{extra}",
                )
            )
        return CalibrationPreview(
            path,
            calibration.source_format,
            tuple(camera.camera for camera in calibration.cameras),
            fingerprint,
            not differences,
            differences,
            calibration,
            tuple(issues),
        )

    def activate(self, project: ProjectManager, preview: CalibrationPreview) -> ImportResult:
        path = Path(preview.source_path)
        verified = self.preview(project, path)
        if verified.fingerprint != preview.fingerprint:
            raise ValueError("标定源文件在预览后发生变化，请重新预览")
        if any(issue.severity == "blocking" for issue in verified.issues):
            raise ValueError("标定相机集合存在阻断问题，不能激活")
        existing = project.manifest.get("calibration")
        if verified.equivalent and isinstance(existing, dict):
            active_value = existing.get("active_path")
            if isinstance(active_value, str):
                return ImportResult(False, project.root / active_value, verified.fingerprint, ())

        active_path = project.root / "calibration" / "source" / path.name
        fingerprint = self.inspect(path)
        affected = tuple(StageGraph().invalidate_from("calibration", "calibration import"))
        manifest = copy.deepcopy(project.manifest)
        stages = manifest.setdefault("stages", {})
        for stage in affected:
            record = stages.setdefault(stage, {"status": "not_started", "generation": 0})
            record["status"] = "pending" if stage == "calibration" else "stale"
            record["generation"] = int(record.get("generation", 0)) + 1
            record["invalidated_reason"] = "calibration import"
        manifest["calibration"] = {
            "active_path": str(active_path.relative_to(project.root)),
            "source_path": str(path.resolve()),
            "source_format": verified.source_format,
            "fingerprint": fingerprint.fingerprint,
            "size": fingerprint.size,
            "modified_at": fingerprint.modified_at,
            "camera_ids": list(fingerprint.camera_ids),
            "differences": list(verified.differences),
        }
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        transaction = ProjectTransaction(project.root)
        transaction.prepare_bytes(active_path.relative_to(project.root), path.read_bytes())
        transaction.prepare_json("manifest.json", manifest)
        transaction.commit()
        project.manifest = manifest
        return ImportResult(True, active_path, fingerprint.fingerprint, affected)

    def import_file(self, project: ProjectManager, path: Path) -> ImportResult:
        return self.activate(project, self.preview(project, path))

    def _active_calibration(self, project: ProjectManager) -> CalibrationSet | None:
        record = project.manifest.get("calibration")
        if not isinstance(record, dict) or not isinstance(record.get("active_path"), str):
            return None
        path = project.root / record["active_path"]
        try:
            return self.repository.load(path)
        except (OSError, ValueError):
            return None
