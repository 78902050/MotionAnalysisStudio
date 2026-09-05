"""Create small, redacted diagnostic archives without copying project inputs."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any


_REQUIRED_MODULES = {
    "PySide6": "PySide6",
    "NumPy": "numpy",
    "OpenCV": "cv2",
    "PyInstaller": "PyInstaller",
    "Pose2Sim": "Pose2Sim",
    "Caliscope": "caliscope",
}
# The one-file desktop bundle embeds the UI runtime. Analysis engines and the
# build tool remain external capabilities and are checked by the full install
# validation path instead of being falsely required by the frozen smoke test.
_EMBEDDED_MODULES = {"PySide6": "PySide6"}
_PACKAGE_NAMES = {
    "PySide6": "PySide6",
    "NumPy": "numpy",
    "OpenCV": "opencv-python",
    "PyInstaller": "pyinstaller",
    "Pose2Sim": "Pose2Sim",
    "Caliscope": "caliscope",
}
_MAX_LOG_BYTES = 2 * 1024 * 1024
_WINDOWS_PATH = re.compile(r"(?i)[a-z]:[\\/][^\r\n\"']+")


@dataclass(frozen=True)
class GuiSmokeResult:
    """Outcome of loading the complete desktop GUI stack."""

    ok: bool
    message: str
    checks: tuple[str, ...]


def run_gui_smoke() -> GuiSmokeResult:
    """Load Qt and construct the real main window without entering its event loop."""

    checks: list[str] = []
    try:
        from PySide6.QtWidgets import QApplication

        checks.append("QtWidgets import")
        application = QApplication.instance()
        if application is None:
            application = QApplication(["MotionAnalysisStudio", "-platform", "offscreen"])
        checks.append("QApplication")

        from app.gui.main_window import MainWindow

        window = MainWindow()
        application.processEvents()
        window.close()
        application.processEvents()
        checks.append("MainWindow")
    except Exception as exc:
        return GuiSmokeResult(False, f"GUI smoke check failed: {type(exc).__name__}: {exc}", tuple(checks))
    return GuiSmokeResult(True, "GUI smoke check passed", tuple(checks))


def run_workflow_smoke() -> GuiSmokeResult:
    """Exercise the frozen correction transaction without external project data."""

    checks: list[str] = []
    try:
        from app.application.quality_correction_service import QualityCorrectionService
        from app.application.pipeline_launcher import build_pipeline_commands
        from app.correction.history import CorrectionHistory
        from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
        from app.domain.issues import QualityIssue
        from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
        from app.pose2sim.config_document import ConfigDocument
        from app.project.discovery import ExistingResultDiscovery
        from app.project.importer import ExistingResultImporter
        from app.project.manager import ProjectManager
        from app.quality.audit import QualityAuditService
        from app.quality.model import QualityReport
        from app.quality.report_store import QualityReportStore

        with tempfile.TemporaryDirectory(prefix="motion-analysis-smoke-") as directory:
            project = ProjectManager.create(Path(directory) / "project", "workflow smoke")
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.manifest["people"] = [{"project_person_id": "person-01"}]
            project.save_manifest()
            pose_path = project.root / "pose" / "cam01.json"
            pose_path.write_text(
                json.dumps(
                    {
                        "camera": "cam01",
                        "model_name": "smoke-model",
                        "keypoint_names": ["left_wrist"],
                        "frames": [
                            {
                                "frame": 0,
                                "people": [
                                    {
                                        "project_person_id": "person-01",
                                        "raw_person_index": 0,
                                        "keypoints": {
                                            "left_wrist": {
                                                "x": 10.0,
                                                "y": 20.0,
                                                "confidence": 0.5,
                                            }
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project.root / "synchronization" / "mapping.json").write_text(
                json.dumps({"offsets": [{"camera": "cam01", "frame_delta": 0, "source": "smoke"}]}),
                encoding="utf-8",
            )
            (project.root / "pose-associated" / "results.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {
                                "camera": "cam01",
                                "frame": 0,
                                "people": [
                                    {"project_person_id": "person-01", "raw_person_index": 0}
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            issue = QualityIssue(
                "workflow-smoke-issue",
                "reprojection",
                "warning",
                FrameAddress("cam01", "pose2d", 0),
                PersonAddress("person-01"),
                KeypointAddress("smoke-model", "left_wrist", 0),
                "workflow smoke",
            )
            QualityReportStore(project).save(
                QualityReport.create("workflow-smoke-report", {}, (issue,), {"pose": "smoke"})
            )
            checks.append("project fixture")

            service = QualityCorrectionService(project)
            resolution = service.resolve_issue(issue)
            if not resolution.can_edit or resolution.edit_target is None:
                raise RuntimeError(resolution.blocker or "quality issue did not resolve")
            session = service.create_session(resolution)
            before = session.document.value_at(resolution.edit_target)
            session.apply_point(resolution.edit_target, before[0] + 1.0, before[1] + 1.0)
            saved_count, _operation_ids = session.save(note="workflow smoke")
            if saved_count != 1:
                raise RuntimeError(f"expected one saved operation, got {saved_count}")
            checks.append("correction save")

            history = CorrectionHistory(project.root)
            if not history.backup_path(pose_path).is_file():
                raise RuntimeError("first-version pose backup was not created")
            if history.restore_file(pose_path, "workflow smoke restore") != 1:
                raise RuntimeError("pose restore did not produce one audit operation")
            checks.append("backup restore")

            existing_root = Path(directory) / "existing-results"
            nested_pose = existing_root / "pose" / "cam01_json" / "cam01_000000.json"
            nested_pose.parent.mkdir(parents=True)
            nested_pose.write_text(
                json.dumps(
                    {
                        "version": 1.3,
                        "people": [
                            {
                                "person_id": [-1],
                                "pose_keypoints_2d": [10.0, 20.0, 0.9],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config_path = existing_root / "config" / "Config.toml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text('[project]\nname = "smoke"\n', encoding="utf-8")
            candidate = ExistingResultDiscovery().discover_one(existing_root)
            existing_project = ExistingResultImporter().register(candidate)
            if candidate.has_video or any(
                "video_path" in camera for camera in existing_project.manifest["cameras"]
            ):
                raise RuntimeError("data-only project unexpectedly requires video")
            quality = QualityAuditService().analyze(existing_project)
            if quality.metrics()["2d_detection_people_count"] != 1:
                raise RuntimeError("nested Pose2Sim detection was not audited")
            checks.append("existing results")

            config = ConfigDocument.open(existing_project.path_for("config"))
            if not config.validate(config.text).valid:
                raise RuntimeError("valid Pose2Sim config was rejected")
            commands = build_pipeline_commands(
                existing_project.path_for("config"), GENERAL_POSE2SIM_STAGES
            )
            if tuple(commands) != GENERAL_POSE2SIM_STAGES:
                raise RuntimeError("general Pose2Sim stage commands are incomplete")
            checks.append("pipeline interface")
    except Exception as exc:
        return GuiSmokeResult(
            False,
            f"Workflow smoke check failed: {type(exc).__name__}: {exc}",
            tuple(checks),
        )
    return GuiSmokeResult(True, "Workflow smoke check passed", tuple(checks))


def validate_installation(include_external: bool = True) -> list[str]:
    """Return actionable missing-capability messages; an empty list means ready."""

    issues: list[str] = []
    if sys.version_info < (3, 12):
        issues.append(f"Python 3.12 or newer is required; found {sys.version.split()[0]}")
    required = _REQUIRED_MODULES if include_external else _EMBEDDED_MODULES
    for label, module_name in required.items():
        try:
            available = find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            issues.append(f"missing runtime capability: {label} ({module_name})")
    return issues


class DiagnosticBundle:
    """Write only redacted diagnostics and small logs into a zip archive."""

    def create(self, project, destination: Path) -> Path:
        root = Path(project.root).resolve()
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination / "diagnostics.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)

        manifest = _redact_value(dict(project.manifest))
        manifest_text = _redact_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", root)
        runtime = {
            "python": sys.version.split()[0],
            "capabilities": {label: _has_module(module) for label, module in _REQUIRED_MODULES.items()},
            "versions": {label: _package_version(package) for label, package in _PACKAGE_NAMES.items()},
        }
        entries: dict[str, str] = {
            "manifest.json": manifest_text,
            "diagnostics/runtime.json": json.dumps(runtime, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            "diagnostics/README.txt": "This bundle contains redacted diagnostics only; project inputs are excluded.\n",
        }
        logs_root = root / "logs"
        if logs_root.is_dir():
            for log_path in sorted(logs_root.glob("*.log")):
                if not log_path.is_file() or log_path.stat().st_size > _MAX_LOG_BYTES:
                    continue
                text = log_path.read_text(encoding="utf-8", errors="replace")
                entries[f"diagnostics/logs/{log_path.name}"] = _redact_text(text, root)

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                archive.writestr(name, entries[name])
        return destination


def _has_module(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def _redact_value(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {str(name): _redact_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, str) and any(token in key.lower() for token in ("path", "root", "directory", "filename", "video")):
        return "<redacted>"
    return value


def _redact_text(text: str, project_root: Path) -> str:
    redacted = text.replace(str(project_root), "<project-root>")
    return _WINDOWS_PATH.sub("<redacted-path>", redacted)
