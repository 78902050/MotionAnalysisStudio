"""Run a copied-workspace acceptance check against recorded project data."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.adapters.pose2sim.pose2d_repository import Pose2DRepository
from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, Trajectory
from app.calibration.importer import CalibrationImporter
from app.application.pipeline_launcher import build_pipeline_commands
from app.correction.history import CorrectionHistory
from app.correction.rerun import CORRECTION_RERUN_STAGES
from app.correction.session import CorrectionSession
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.external_tools.caliscope_settings import CaliscopeSettingsDiagnostic
from app.external_tools.model import build_caliscope_command
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.pose2sim.config_document import ConfigDocument
from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter
from app.project.manager import ProjectManager
from app.quality.audit import QualityAuditService


def _first_valid_calibration(root: Path, importer: CalibrationImporter) -> Path:
    failures: list[str] = []
    for path in root.rglob("camera_array.toml"):
        try:
            if path.stat().st_size < 100:
                continue
            importer.inspect(path)
            return path
        except (OSError, ValueError) as exc:
            failures.append(f"{path}: {exc}")
    detail = f"; first failure: {failures[0]}" if failures else ""
    raise FileNotFoundError(f"no readable camera_array.toml found under {root}{detail}")


def _first_valid_trajectory(root: Path) -> tuple[Path, Trajectory]:
    failures: list[str] = []
    for path in root.rglob("*.trc"):
        try:
            return path, Trajectory.from_trc(path, "world")
        except (OSError, UnicodeError, ValueError) as exc:
            failures.append(f"{path}: {exc}")
    detail = f"; first failure: {failures[0]}" if failures else ""
    raise FileNotFoundError(f"no readable TRC found under {root}{detail}")


def _first_valid_pose(root: Path) -> tuple[Path, str, int, int]:
    failures: list[str] = []
    for directory in root.rglob("*_json"):
        if not directory.is_dir():
            continue
        camera = directory.name.removesuffix("_json")
        for path in directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                people = payload.get("people") if isinstance(payload, dict) else None
                if not isinstance(people, list) or not people or not isinstance(people[0], dict):
                    continue
                values = people[0].get("pose_keypoints_2d")
                if not isinstance(values, list) or not values or len(values) % 3:
                    continue
                if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
                    continue
                frame_text = path.stem.rsplit("_", 1)[-1]
                if not frame_text.isdigit():
                    continue
                return path, camera, int(frame_text), len(values) // 3
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                failures.append(f"{path}: {exc}")
    detail = f"; first failure: {failures[0]}" if failures else ""
    raise FileNotFoundError(f"no readable Pose2Sim frame JSON found under {root}{detail}")


def _verify_existing_results_trial(
    source_root: Path,
    output_root: Path,
    calibration_source: Path,
    fallback_trc: Path,
) -> dict[str, object]:
    discovery = ExistingResultDiscovery()
    candidates = discovery.scan(source_root)
    source_candidate = next(
        (candidate for candidate in candidates if candidate.artifacts.pose_2d),
        None,
    )
    if source_candidate is None:
        raise FileNotFoundError(f"no processed Pose2Sim trial found under {source_root}")
    pose_source, camera, _frame, _keypoint_count = _first_valid_pose(source_candidate.root)
    trc_source = source_candidate.artifacts.trc[0] if source_candidate.artifacts.trc else fallback_trc

    trial = output_root / "registered-trial"
    pose_target = trial / "pose" / f"{camera}_json" / pose_source.name
    pose_target.parent.mkdir(parents=True, exist_ok=True)
    (trial / "pose-3d").mkdir(parents=True, exist_ok=True)
    (trial / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(pose_source, pose_target)
    shutil.copy2(trc_source, trial / "pose-3d" / trc_source.name)
    shutil.copy2(calibration_source, trial / "camera_array.toml")
    (trial / "config" / "Config.toml").write_text(
        '[project]\nname = "existing-results-acceptance"\n',
        encoding="utf-8",
    )

    copied_candidate = discovery.discover_one(trial)
    project = ExistingResultImporter().register(copied_candidate)
    quality = QualityAuditService()
    report = quality.analyze(project)
    quality.save(report)
    config = ConfigDocument.open(project.path_for("config"))
    config_validation = config.validate(config.text)
    commands = build_pipeline_commands(project.path_for("config"), GENERAL_POSE2SIM_STAGES)
    settings_inspection = CaliscopeSettingsDiagnostic.inspect(
        CaliscopeSettingsDiagnostic.default_path()
    )
    return {
        "discovered_trial_count": len(candidates),
        "source_trial": str(source_candidate.root),
        "registered_root": str(project.root),
        "cameras": list(copied_candidate.cameras),
        "has_video": copied_candidate.has_video,
        "quality_report": str(project.path_for("quality_report")),
        "quality_2d_detection_people_count": report.metrics()["2d_detection_people_count"],
        "config_valid": config_validation.valid,
        "general_pose2sim_stages": list(GENERAL_POSE2SIM_STAGES),
        "pipeline_command_stages": list(commands),
        "caliscope_command": list(build_caliscope_command(project.root)),
        "caliscope_settings": {
            "path": str(settings_inspection.path),
            "encoding": settings_inspection.encoding,
            "valid": settings_inspection.valid,
            "message": settings_inspection.message,
        },
    }


def run_acceptance(source_root: Path, output_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"real data root not found: {source_root}")
    if output_root == source_root or output_root.is_relative_to(source_root):
        raise ValueError("acceptance output must be outside the source data root")
    output_root.mkdir(parents=True, exist_ok=False)

    importer = CalibrationImporter()
    calibration_source = _first_valid_calibration(source_root, importer)
    trc_source, trajectory = _first_valid_trajectory(source_root)
    pose_source, camera, frame, keypoint_count = _first_valid_pose(source_root)
    pose_source_before = pose_source.read_bytes()

    project = ProjectManager.create(output_root / "project", "真实数据验收")
    calibration_copy = output_root / "inputs" / "camera_array.toml"
    trc_copy = output_root / "inputs" / trc_source.name
    pose_copy = project.root / "pose" / f"{camera}_json" / pose_source.name
    calibration_copy.parent.mkdir(parents=True, exist_ok=True)
    pose_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(calibration_source, calibration_copy)
    shutil.copy2(trc_source, trc_copy)
    shutil.copy2(pose_source, pose_copy)

    import_result = importer.import_file(project, calibration_copy)
    calibration = importer.repository.load(import_result.active_path)
    project.manifest["cameras"] = [
        {"camera_id": record.camera} for record in calibration.cameras
    ]
    project.manifest["people"] = [{"project_person_id": "person-acceptance"}]
    videos = [str(path.resolve()) for path in source_root.rglob("*.mp4")]
    project.manifest["media_references"] = videos[:1]
    project.save_manifest()

    copied_trajectory = Trajectory.from_trc(trc_copy, "world")
    keypoint_names = tuple(f"keypoint-{index:03d}" for index in range(keypoint_count))
    repository = Pose2DRepository(
        project.root / "pose",
        keypoint_names,
        project_root=project.root,
        model_name="acceptance-indexed",
    )
    document = repository.load_frame(camera, frame)
    target = CorrectionTarget(
        FrameAddress(camera, "raw", frame),
        PersonAddress("raw-0", None, 0),
        KeypointAddress("acceptance-indexed", keypoint_names[0], 0),
    )
    before = document.value_at(target)
    if not all(math.isfinite(value) for value in before):
        raise ValueError(f"first Pose2Sim keypoint is not finite: {pose_source}")
    session = CorrectionSession(document, project_root=project.root, session_id="real-data")
    session.apply_point(target, before[0] + 0.5, before[1] + 0.5)
    saved_count, operation_ids = session.save(note="real data acceptance")
    history = CorrectionHistory(project.root)
    backup_path = history.backup_path(pose_copy)
    restored_count = history.restore_file(pose_copy, "real data acceptance restore")
    restored = repository.load_frame(camera, frame).value_at(target)
    if restored != before:
        raise AssertionError(f"restored point differs from source: {restored!r} != {before!r}")
    if pose_source.read_bytes() != pose_source_before:
        raise AssertionError(f"source Pose2Sim JSON was modified: {pose_source}")
    if "poseEstimation" in CORRECTION_RERUN_STAGES:
        raise AssertionError("correction rerun stages unexpectedly contain poseEstimation")

    sampling_rate = float(copied_trajectory.metadata["sampling_rate_hz"])
    metric = MetricEngine().calculate(
        copied_trajectory,
        (MetricDefinition(f"speed:{copied_trajectory.labels[0]}", f"{copied_trajectory.coordinate_unit}/s", (copied_trajectory.labels[0],)),),
        MetricConfig(sampling_rate, copied_trajectory.coordinate_unit, None),
    )
    result: dict[str, object] = {
        "status": "passed",
        "source_root": str(source_root),
        "output_root": str(output_root),
        "calibration": {
            "source": str(calibration_source),
            "camera_count": len(calibration.cameras),
            "camera_ids": [record.camera for record in calibration.cameras],
        },
        "trajectory": {
            "source": str(trc_source),
            "frame_count": len(copied_trajectory.frames),
            "label_count": len(copied_trajectory.labels),
            "unit": copied_trajectory.coordinate_unit,
            "sampling_rate_hz": sampling_rate,
            "metric_columns": list(metric.columns),
        },
        "pose2d": {
            "source": str(pose_source),
            "camera": camera,
            "frame": frame,
            "person_count": len(document.frame_pose().people),
            "keypoint_count": keypoint_count,
            "saved_operations": saved_count,
            "operation_ids": operation_ids,
            "restored_operations": restored_count,
            "backup": str(backup_path),
            "source_unchanged": True,
        },
        "correction_rerun_stages": list(CORRECTION_RERUN_STAGES),
        "video_reference": videos[0] if videos else None,
    }
    result["existing_results"] = _verify_existing_results_trial(
        source_root,
        output_root,
        calibration_source,
        trc_source,
    )
    if saved_count != 1 or restored_count != 1 or not backup_path.is_file():
        raise AssertionError("pose correction save/backup/restore acceptance failed")
    report_path = output_root / "acceptance.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_acceptance(arguments.root, arguments.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
