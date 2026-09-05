"""Per-camera calibration quality diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.adapters.caliscope.calibration_repository import CaliscopeCalibrationRepository
from app.project.manager import ProjectManager

from .importer import CalibrationImporter
from .model import CalibrationCameraReport, CalibrationIssue, CalibrationReport


class CalibrationDiagnostics:
    def analyze(self, project: ProjectManager) -> CalibrationReport:
        record = project.manifest.get("calibration")
        if not isinstance(record, dict) or not isinstance(record.get("active_path"), str):
            return CalibrationReport(
                active_path=None,
                fingerprint=None,
                camera_ids=(),
                cameras=(),
                issues=(CalibrationIssue("blocking", "没有可用的激活标定文件"),),
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
        active_path = project.root / Path(record["active_path"])
        try:
            fingerprint = CalibrationImporter().inspect(active_path)
            calibration = CaliscopeCalibrationRepository().load(active_path)
        except (FileNotFoundError, ValueError) as exc:
            return CalibrationReport(
                active_path=active_path,
                fingerprint=record.get("fingerprint") if isinstance(record.get("fingerprint"), str) else None,
                camera_ids=(),
                cameras=(),
                issues=(CalibrationIssue("blocking", f"激活标定文件不可读：{exc}"),),
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        camera_reports: list[CalibrationCameraReport] = []
        actual_ids: list[str] = []
        for item in calibration.cameras:
            camera_id = item.camera
            actual_ids.append(camera_id)
            camera_reports.append(
                CalibrationCameraReport(
                    camera_id=camera_id,
                    reprojection_error=item.reprojection_error,
                    coverage=None,
                )
            )

        expected_ids = {
            str(item["camera_id"])
            for item in project.manifest.get("cameras", [])
            if isinstance(item, dict) and isinstance(item.get("camera_id"), str)
        }
        issues: list[CalibrationIssue] = []
        for camera_id in sorted(expected_ids - set(actual_ids)):
            issues.append(CalibrationIssue("blocking", f"激活标定文件缺少相机 {camera_id}", camera_id))
        for camera_id in sorted(set(actual_ids) - expected_ids) if expected_ids else ():
            issues.append(CalibrationIssue("warning", f"激活标定文件包含项目未配置相机 {camera_id}", camera_id))
        return CalibrationReport(
            active_path=active_path,
            fingerprint=fingerprint.fingerprint,
            camera_ids=tuple(actual_ids),
            cameras=tuple(camera_reports),
            issues=tuple(issues),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
