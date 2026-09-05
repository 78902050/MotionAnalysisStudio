"""Register existing Pose2Sim results as a managed project in place."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.calibration.importer import CalibrationImporter
from app.io.atomic import AtomicJsonStore

from .import_model import TrialCandidate
from .manager import ProjectManager
from .manifest import utc_now


class ExistingResultImporter:
    def register(self, candidate: TrialCandidate) -> ProjectManager:
        root = candidate.root.resolve()
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            return ProjectManager.open(root)

        project = ProjectManager.create(root, root.name)
        calibration_loaded = False
        if candidate.calibration_path is not None:
            try:
                CalibrationImporter().import_file(project, candidate.calibration_path)
                calibration_loaded = True
            except (OSError, ValueError):
                calibration_loaded = False

        cameras: list[dict[str, object]] = []
        for camera in candidate.cameras:
            record: dict[str, object] = {"camera_id": camera}
            video = self._video_for(camera, candidate.source_videos)
            if video is not None:
                record["video_path"] = str(video)
            cameras.append(record)
        project.manifest["cameras"] = cameras

        target_config = project.path_for("config")
        if (
            candidate.config_path is not None
            and candidate.config_state == "valid"
            and candidate.config_path.resolve() != target_config.resolve()
            and target_config.stat().st_size == 0
        ):
            shutil.copy2(candidate.config_path, target_config)

        stage_evidence = {
            "calibration": calibration_loaded,
            "synchronization": bool(candidate.artifacts.pose_sync),
            "poseEstimation": bool(candidate.artifacts.pose_2d),
            "personAssociation": bool(candidate.artifacts.pose_associated),
            "triangulation": bool(candidate.artifacts.trc),
            "kinematics": bool(candidate.artifacts.kinematics),
        }
        stages = project.manifest["stages"]
        for stage, available in stage_evidence.items():
            if available:
                stages[stage]["status"] = "completed"
                stages[stage]["imported"] = True

        imported_at = utc_now()
        artifact_report = {
            "trial_root": str(root),
            "imported_at": imported_at,
            "cameras": list(candidate.cameras),
            "pose_2d_files": candidate.artifacts.pose_2d,
            "pose_sync_files": candidate.artifacts.pose_sync,
            "pose_associated_files": candidate.artifacts.pose_associated,
            "trc_files": [str(path) for path in candidate.artifacts.trc],
            "kinematics_files": [str(path) for path in candidate.artifacts.kinematics],
            "calibration_path": str(candidate.calibration_path) if candidate.calibration_path else None,
            "config_path": str(candidate.config_path) if candidate.config_path else None,
            "config_state": candidate.config_state,
            "source_videos": [str(path) for path in candidate.source_videos],
            "derived_videos": [str(path) for path in candidate.derived_videos],
            "has_video": candidate.has_video,
        }
        project.manifest["imported_artifacts"] = artifact_report
        project.manifest["updated_at"] = imported_at
        project.save_manifest()
        AtomicJsonStore.replace(root / "reports" / "import" / "artifacts.json", artifact_report)
        return project

    @staticmethod
    def _video_for(camera: str, videos: tuple[Path, ...]) -> Path | None:
        matches = [
            path
            for path in videos
            if path.stem.casefold() == camera.casefold()
            or path.stem.casefold().startswith(f"{camera.casefold()}_")
        ]
        return matches[0] if matches else None

