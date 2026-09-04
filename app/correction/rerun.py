"""Selective Pose2Sim rerun rules for confirmed 2D corrections."""

from __future__ import annotations

from typing import Protocol

from app.adapters.pose2sim.runner import RunResult
from app.domain.stages import StageGraph
from app.project.manifest import utc_now
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest


CORRECTION_RERUN_STAGES: tuple[str, ...] = (
    "triangulation",
    "filtering",
    "markerAugmentation",
    "kinematics",
)


class _Runner(Protocol):
    def run(self, request: TaskRequest, stages: tuple[str, ...]) -> RunResult: ...


def invalidate_from(
    project: ProjectManager,
    stage: str,
    reason: str,
    operation_id: str | None = None,
) -> list[str]:
    affected = StageGraph().invalidate_from(stage, reason, operation_id)
    stages = project.manifest.setdefault("stages", {})
    for name in affected:
        record = stages.setdefault(name, {"status": "not_started", "generation": 0})
        record["status"] = "pending" if name == stage else "stale"
        record["generation"] = int(record.get("generation", 0)) + 1
        record["invalidated_reason"] = reason
        if operation_id is not None:
            record["invalidated_by"] = operation_id
    project.manifest["updated_at"] = utc_now()
    project.save_manifest()
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
    result = runner.run(request, stages)
    if result.project_id != request.project_id or result.generation != request.generation:
        return result

    if result.succeeded:
        for stage in stages:
            record = manifest_stages.setdefault(stage, {})
            record["status"] = "completed"
            record["completed_at"] = utc_now()
    elif result.cancelled:
        for stage in stages:
            manifest_stages.setdefault(stage, {})["status"] = "pending"
    else:
        for stage in stages:
            manifest_stages.setdefault(stage, {})["status"] = "stale"
    project.manifest["updated_at"] = utc_now()
    project.save_manifest()
    return result
