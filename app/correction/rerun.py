"""Selective Pose2Sim rerun rules for confirmed 2D corrections."""

from __future__ import annotations

from typing import Protocol

from app.adapters.pose2sim.runner import RunResult
from app.pipeline.dependency_graph import StageGraph
from app.project.manifest import utc_now
from app.project.manager import ProjectManager
from app.quality.reporting import RerunQualityReporter
from app.tasks.base import TaskRequest


CORRECTION_RERUN_STAGES = StageGraph().executable_rerun_stages_for("2d_correction")


class _Runner(Protocol):
    def run(self, request: TaskRequest, stages: tuple[str, ...]) -> RunResult: ...


def invalidate_from(
    project: ProjectManager,
    stage: str,
    reason: str,
    operation_id: str | None = None,
) -> list[str]:
    affected = project.invalidate_from(
        stage, reason, [operation_id] if operation_id is not None else []
    )
    return [name for name in affected if name in CORRECTION_RERUN_STAGES]


def run_correction_rerun(project: ProjectManager, session_id: str, runner: _Runner) -> RunResult:
    if not session_id.strip():
        raise ValueError("session_id must not be empty")
    stages = tuple(CORRECTION_RERUN_STAGES)
    if "poseEstimation" in stages:
        raise AssertionError("correction rerun must not include poseEstimation")
    manifest_stages = project.manifest.setdefault("stages", {})
    generation = max(
        [int(record.get("generation", 0)) for record in manifest_stages.values() if isinstance(record, dict)]
        or [0]
    )
    request = TaskRequest(
        project_id=str(project.manifest["project_id"]),
        generation=generation,
        name="correction-rerun",
        payload={"working_directory": str(project.root), "session_id": session_id},
    )
    reporter = RerunQualityReporter(project)
    before_report = reporter.current_or_none()
    reporter.mark_started(before_report)
    result = runner.run(request, stages)
    if result.project_id != request.project_id or result.generation != request.generation:
        reporter.fail(before_report, result)
        return result

    if result.succeeded:
        for stage in stages:
            record = manifest_stages.setdefault(stage, {})
            record["status"] = "completed"
            record["completed_at"] = utc_now()
        reporter.complete(before_report)
    elif result.cancelled:
        for stage in stages:
            manifest_stages.setdefault(stage, {})["status"] = "pending"
        reporter.fail(before_report, result)
    else:
        for stage in stages:
            manifest_stages.setdefault(stage, {})["status"] = "stale"
        reporter.fail(before_report, result)
    project.manifest["updated_at"] = utc_now()
    project.save_manifest()
    return result
