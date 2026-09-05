"""Supervised execution of user-selected Pose2Sim stages."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from app.adapters.pose2sim.runner import PipelineRunner, RunResult
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.pose2sim.config_document import ConfigDocument
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
    executable: Path | None = None,
    frozen: bool | None = None,
) -> dict[str, tuple[str, ...]]:
    selected = tuple(stages)
    if not selected:
        raise ValueError("at least one Pose2Sim stage is required")
    invalid = [stage for stage in selected if stage not in GENERAL_POSE2SIM_STAGES]
    if invalid:
        raise ValueError(f"Pose2Sim stages are not allowed: {', '.join(invalid)}")
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
        )
        for stage in selected
    }


class PipelineLauncher:
    def __init__(
        self,
        controller: ApplicationController,
        *,
        runner_factory: Callable[..., Any] = PipelineRunner,
    ) -> None:
        self.controller = controller
        self.runner_factory = runner_factory
        self._log_paths: dict[str, Path] = {}

    def start(self, project: ProjectManager, stages: Iterable[str]) -> TaskHandle:
        selected = tuple(stages)
        commands = build_pipeline_commands(project.path_for("config"), selected)
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
