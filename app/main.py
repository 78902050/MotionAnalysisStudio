"""Application entry point for the desktop UI and package smoke checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.diagnostics.bundle import run_gui_smoke, validate_installation
from app.correction.rerun import CORRECTION_RERUN_STAGES


def run_pose2sim_stage(stage: str, config_path: Path) -> int:
    if stage not in CORRECTION_RERUN_STAGES:
        raise ValueError(f"Pose2Sim stage is not allowed: {stage}")
    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Pose2Sim config not found: {config_path}")
    from Pose2Sim.Pose2Sim import (
        filtering,
        kinematics,
        markerAugmentation,
        personAssociation,
        triangulation,
    )

    stages = {
        "personAssociation": personAssociation,
        "triangulation": triangulation,
        "filtering": filtering,
        "markerAugmentation": markerAugmentation,
        "kinematics": kinematics,
    }
    stages[stage](config=str(config_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Motion Analysis Studio")
    parser.add_argument("--smoke-test", action="store_true", help="validate runtime capabilities without opening the UI")
    parser.add_argument(
        "--gui-smoke-test",
        action="store_true",
        help="load Qt and construct the main window without entering the UI event loop",
    )
    parser.add_argument("--pose2sim-stage", choices=CORRECTION_RERUN_STAGES)
    parser.add_argument("--pose2sim-config", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.pose2sim_stage is not None:
        if arguments.pose2sim_config is None:
            parser.error("--pose2sim-config is required with --pose2sim-stage")
        return run_pose2sim_stage(arguments.pose2sim_stage, arguments.pose2sim_config)
    if arguments.gui_smoke_test:
        result = run_gui_smoke()
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
