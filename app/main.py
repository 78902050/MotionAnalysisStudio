"""Application entry point for the desktop UI and package smoke checks."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from app.diagnostics.bundle import run_gui_smoke, run_workflow_smoke, validate_installation
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.pose2sim.runtime_diagnostics import (
    inspect_openvino_runtime,
    require_pose_estimation_runtime,
)


def run_pose2sim_stage(stage: str, config_path: Path, project_root: Path) -> int:
    if stage not in GENERAL_POSE2SIM_STAGES:
        raise ValueError(f"Pose2Sim stage is not allowed: {stage}")
    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Pose2Sim config not found: {config_path}")
    project_root = Path(project_root).resolve()
    config_data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    project_config = config_data.setdefault("project", {})
    if not isinstance(project_config, dict):
        raise ValueError("Pose2Sim [project] configuration must be a table")
    project_config["project_dir"] = str(project_root)
    if stage == "poseEstimation":
        require_pose_estimation_runtime()
    from Pose2Sim.Pose2Sim import (
        filtering,
        calibration,
        kinematics,
        markerAugmentation,
        personAssociation,
        poseEstimation,
        synchronization,
        triangulation,
    )

    stages = {
        "calibration": calibration,
        "synchronization": synchronization,
        "poseEstimation": poseEstimation,
        "personAssociation": personAssociation,
        "triangulation": triangulation,
        "filtering": filtering,
        "markerAugmentation": markerAugmentation,
        "kinematics": kinematics,
    }
    stages[stage](config=config_data)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Motion Analysis Studio")
    parser.add_argument("--smoke-test", action="store_true", help="validate runtime capabilities without opening the UI")
    parser.add_argument(
        "--gui-smoke-test",
        action="store_true",
        help="load Qt and construct the main window without entering the UI event loop",
    )
    parser.add_argument(
        "--workflow-smoke-test",
        action="store_true",
        help="exercise quality issue resolution and an auditable correction transaction",
    )
    parser.add_argument(
        "--pose2sim-runtime-check",
        action="store_true",
        help="check whether the current runtime can load OpenVINO ONNX models",
    )
    parser.add_argument("--pose2sim-stage", choices=GENERAL_POSE2SIM_STAGES)
    parser.add_argument("--pose2sim-config", type=Path)
    parser.add_argument("--pose2sim-project-root", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.pose2sim_runtime_check:
        report = inspect_openvino_runtime()
        frontends = ", ".join(report.available_frontends) or "无"
        devices = ", ".join(report.available_devices) or "无"
        message = f"{report.user_message} 可用前端：{frontends}；可用设备：{devices}"
        if report.technical_detail and not report.ok:
            message = f"{message}\n{report.technical_detail}"
        print(message, file=sys.stdout if report.ok else sys.stderr)
        return 0 if report.ok else 1
    if arguments.pose2sim_stage is not None:
        if arguments.pose2sim_config is None:
            parser.error("--pose2sim-config is required with --pose2sim-stage")
        if arguments.pose2sim_project_root is None:
            parser.error("--pose2sim-project-root is required with --pose2sim-stage")
        return run_pose2sim_stage(
            arguments.pose2sim_stage,
            arguments.pose2sim_config,
            arguments.pose2sim_project_root,
        )
    if arguments.gui_smoke_test:
        result = run_gui_smoke()
        print(result.message, file=sys.stdout if result.ok else sys.stderr)
        return 0 if result.ok else 1
    if arguments.workflow_smoke_test:
        result = run_workflow_smoke()
        print(result.message, file=sys.stdout if result.ok else sys.stderr)
        return 0 if result.ok else 1
    if arguments.smoke_test:
        issues = validate_installation(include_external=False)
        if issues:
            for issue in issues:
                print(issue, file=sys.stderr)
            return 1
        print("Motion Analysis Studio smoke test: OK")
        return 0

    from PySide6.QtWidgets import QApplication

    qt_args = [sys.argv[0], *(argv if argv is not None else sys.argv[1:])]
    application = QApplication(qt_args)
    from app.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
