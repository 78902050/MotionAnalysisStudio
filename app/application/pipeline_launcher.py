"""Supervised execution of user-selected Pose2Sim stages."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from app.adapters.pose2sim.runner import PipelineRunner, RunResult
from app.media.importer import ANALYSIS_VIDEO_SUFFIXES
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.pose2sim.config_document import ConfigDocument
from app.pose2sim.runtime_diagnostics import classify_pose2sim_failure
from app.project.discovery import ExistingResultDiscovery
from app.project.manager import ProjectManager
from app.project.manifest import utc_now
from app.tasks.base import CancellationToken, TaskCancelled, TaskRequest
from app.tasks.handle import TaskHandle

from .controller import ApplicationController


def build_pipeline_commands(
    config_path: Path,
    stages: Iterable[str] = GENERAL_POSE2SIM_STAGES,
    *,
    project_root: Path,
    executable: Path | None = None,
    frozen: bool | None = None,
    pose2sim_python: Path | None = None,
) -> dict[str, tuple[str, ...]]:
    selected = tuple(stages)
    if not selected:
        raise ValueError("at least one Pose2Sim stage is required")
    invalid = [stage for stage in selected if stage not in GENERAL_POSE2SIM_STAGES]
    if invalid:
        raise ValueError(f"Pose2Sim stages are not allowed: {', '.join(invalid)}")
    if pose2sim_python is not None:
        python = Path(pose2sim_python)
        script = (
            "import sys, tomllib\n"
            "from pathlib import Path\n"
            "if sys.argv[1] == 'poseEstimation':\n"
            "    from openvino.frontend import FrontEndManager\n"
            "    frontends = {str(name).casefold() for name in FrontEndManager().get_available_front_ends()}\n"
            "    if 'onnx' not in frontends:\n"
            "        raise RuntimeError('MAS_POSE_RUNTIME_ONNX_MISSING: available_frontends=' + ','.join(sorted(frontends)))\n"
            "    from openvino import Core\n"
            "    devices = {str(name).upper() for name in Core().available_devices}\n"
            "    if not any(name == 'CPU' or name.startswith('CPU.') for name in devices):\n"
            "        raise RuntimeError('MAS_POSE_RUNTIME_CPU_MISSING: available_devices=' + ','.join(sorted(devices)))\n"
            "from Pose2Sim import Pose2Sim as module\n"
            "config = tomllib.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
            "project = config.setdefault('project', {})\n"
            "project['project_dir'] = str(Path(sys.argv[3]).resolve())\n"
            "getattr(module, sys.argv[1])(config=config)\n"
        )
        return {
            stage: (
                str(python), "-c", script, stage,
                str(Path(config_path)), str(Path(project_root)),
            )
            for stage in selected
        }
    executable = Path(executable or sys.executable)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    prefix = (str(executable),) if is_frozen else (str(executable), "-m", "app.main")
    return {
        stage: (
            *prefix,
            "--pose2sim-stage",
            stage,
            "--pose2sim-config",
            str(Path(config_path)),
            "--pose2sim-project-root",
            str(Path(project_root)),
        )
        for stage in selected
    }


class PipelineLauncher:
    def __init__(
        self,
        controller: ApplicationController,
        *,
        runner_factory: Callable[..., Any] = PipelineRunner,
        pose2sim_python_provider: Callable[[], Path | None] | None = None,
    ) -> None:
        self.controller = controller
        self.runner_factory = runner_factory
        self.pose2sim_python_provider = pose2sim_python_provider or (lambda: None)
        self._log_paths: dict[str, Path] = {}

    def start(self, project: ProjectManager, stages: Iterable[str]) -> TaskHandle:
        selected = tuple(stages)
        config_document = ConfigDocument.open(project.path_for("config"))
        validation = config_document.validate(config_document.text)
        if not validation.valid:
            raise ValueError(validation.message)
        project_id = str(project.manifest["project_id"])
        generation = self.controller.generation
        if self.controller.current_project is not project:
            raise ValueError("pipeline project is not the current project")
        if any(
            snapshot.project_id == project_id
            and snapshot.generation == generation
            and snapshot.name == "pose2sim-pipeline"
            and snapshot.status in {"queued", "running", "cancelling"}
            for snapshot in self.controller.supervisor.snapshots()
        ):
            raise RuntimeError("当前项目已有 Pose2Sim 流程任务")
        if "poseEstimation" in selected and not self._has_analysis_video(project.root):
            raise ValueError("二维姿态估计需要分析视频，请先在“视频素材”页面导入视频")
        commands = build_pipeline_commands(
            project.path_for("config"),
            selected,
            project_root=project.root,
            pose2sim_python=self.pose2sim_python_provider(),
        )

        log_file = f"pose2sim-{uuid4().hex}.log"
        log_path = project.path_for("logs") / log_file
        request = TaskRequest(
            project_id,
            generation,
            "pose2sim-pipeline",
            {
                "working_directory": str(project.root),
                "log_file": log_file,
                "stages": list(selected),
            },
        )
        stage_manifest = project.manifest.setdefault("stages", {})
        for index, stage in enumerate(selected):
            record = stage_manifest.setdefault(stage, {})
            record["status"] = "running" if index == 0 else "pending"
            record["started_at"] = utc_now() if index == 0 else None
        project.manifest["updated_at"] = utc_now()
        project.save_manifest()

        def work(token: CancellationToken) -> RunResult:
            runner = self.runner_factory(
                commands,
                GENERAL_POSE2SIM_STAGES,
                project.path_for("logs"),
            )
            pipeline_handle = runner.start(request, selected)
            while True:
                if token.is_cancelled:
                    pipeline_handle.cancel()
                try:
                    result = pipeline_handle.wait(0.05)
                    break
                except TimeoutError:
                    continue
            if not result.succeeded and not result.cancelled:
                classified = classify_pose2sim_failure(
                    self._read_log_tail(result.log_path),
                    result.failed_stage,
                )
                if classified is not None:
                    result = replace(result, error=classified)
            self._record_result(project, selected, result)
            if result.cancelled:
                raise TaskCancelled()
            if not result.succeeded:
                raise RuntimeError(
                    f"阶段 {result.failed_stage or '未知'} 失败；日志：{result.log_path}；{result.error or ''}"
                )
            return result

        handle = self.controller.start_task(request, work)
        self._log_paths[handle.task_id] = log_path
        return handle

    @staticmethod
    def _read_log_tail(path: Path, limit: int = 256 * 1024) -> str:
        try:
            with Path(path).open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                return handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _has_analysis_video(project_root: Path) -> bool:
        videos = Path(project_root) / "videos"
        return videos.is_dir() and any(
            path.is_file() and path.suffix.casefold() in ANALYSIS_VIDEO_SUFFIXES
            for path in videos.iterdir()
        )

    def log_path_for(self, task_id: str) -> Path | None:
        return self._log_paths.get(task_id)

    @staticmethod
    def _record_result(
        project: ProjectManager,
        selected: tuple[str, ...],
        result: RunResult,
    ) -> None:
        try:
            manifest_log_path = result.log_path.resolve().relative_to(project.root.resolve()).as_posix()
        except ValueError:
            manifest_log_path = str(result.log_path)
        records = {record.stage: record for record in result.stage_results}
        stage_manifest = project.manifest.setdefault("stages", {})
        for stage in selected:
            manifest_record = stage_manifest.setdefault(stage, {})
            stage_result = records.get(stage)
            if stage_result is None:
                manifest_record["status"] = "pending"
                continue
            manifest_record.update(
                {
                    "status": (
                        "completed"
                        if stage_result.status == "completed"
                        else "pending"
                        if stage_result.status == "cancelled"
                        else "failed"
                    ),
                    "started_at": stage_result.started_at,
                    "finished_at": stage_result.finished_at,
                    "duration_seconds": stage_result.duration_seconds,
                    "exit_code": stage_result.exit_code,
                    "log_path": manifest_log_path,
                }
            )
        project.manifest["last_pipeline_run"] = {
            "stages": list(selected),
            "succeeded": result.succeeded,
            "cancelled": result.cancelled,
            "failed_stage": result.failed_stage,
            "error": result.error,
            "log_path": manifest_log_path,
            "finished_at": utc_now(),
        }
        if result.succeeded:
            try:
                candidate = ExistingResultDiscovery().discover_one(project.root)
            except (OSError, ValueError):
                candidate = None
            if candidate is not None:
                project.manifest["artifact_inventory"] = {
                    "pose_2d_files": candidate.artifacts.pose_2d,
                    "pose_sync_files": candidate.artifacts.pose_sync,
                    "pose_associated_files": candidate.artifacts.pose_associated,
                    "trc_files": [str(path) for path in candidate.artifacts.trc],
                    "kinematics_files": [str(path) for path in candidate.artifacts.kinematics],
                    "scanned_at": utc_now(),
                }
        project.manifest["updated_at"] = utc_now()
        project.save_manifest()
