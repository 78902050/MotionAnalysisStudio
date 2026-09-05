"""Launch correction-dependent Pose2Sim stages through the shared task supervisor."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.adapters.pose2sim.runner import PipelineRunner, RunResult
from app.correction.rerun import CORRECTION_RERUN_STAGES, run_correction_rerun
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskCancelled, TaskRequest

from .controller import ApplicationController


def build_stage_commands(
    config_path: Path,
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> dict[str, tuple[str, ...]]:
    """Build commands that work both from Python and from the packaged executable."""
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
        for stage in CORRECTION_RERUN_STAGES
    }


class _CancellationAwareRunner:
    def __init__(self, runner: PipelineRunner, token: CancellationToken) -> None:
        self.runner = runner
        self.token = token

    def run(self, request: TaskRequest, stages: tuple[str, ...]) -> RunResult:
        handle = self.runner.start(request, stages)
        cancellation_sent = False
        while True:
            if self.token.is_cancelled and not cancellation_sent:
                handle.cancel()
                cancellation_sent = True
            try:
                return handle.wait(0.05)
            except TimeoutError:
                continue


class CorrectionRerunLauncher:
    """Callable controller handler for one supervised selective rerun."""

    def __init__(
        self,
        controller: ApplicationController,
        *,
        runner_factory: Callable[..., Any] = PipelineRunner,
    ) -> None:
        self.controller = controller
        self.runner_factory = runner_factory

    def __call__(self, project: ProjectManager, session_id: str) -> bool:
        project_id = str(project.manifest["project_id"])
        generation = self.controller.generation
        if any(
            snapshot.project_id == project_id
            and snapshot.generation == generation
            and snapshot.name == "correction-rerun"
            and snapshot.status in {"queued", "running", "cancelling"}
            for snapshot in self.controller.supervisor.snapshots()
        ):
            self.controller.last_error = "当前项目已有选择性重跑任务"
            return False

        config_path = project.path_for("config")
        commands = build_stage_commands(config_path)
        request = TaskRequest(
            project_id,
            generation,
            "correction-rerun",
            {"session_id": session_id, "working_directory": str(project.root)},
        )

        def work(token: CancellationToken) -> RunResult:
            runner = self.runner_factory(
                commands,
                tuple(CORRECTION_RERUN_STAGES),
                project.path_for("logs"),
            )
            result = run_correction_rerun(
                project,
                session_id,
                _CancellationAwareRunner(runner, token),
            )
            if result.cancelled:
                raise TaskCancelled()
            if not result.succeeded:
                raise RuntimeError(result.error or f"阶段失败：{result.failed_stage or '未知'}")
            return result

        self.controller.start_task(request, work)
        return True
