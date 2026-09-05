"""Single dependency graph for invalidation and selective reruns."""

from __future__ import annotations

from collections import deque
from typing import Iterable

STAGES: tuple[str, ...] = (
    "calibration",
    "synchronization",
    "poseEstimation",
    "personAssociation",
    "triangulation",
    "filtering",
    "markerAugmentation",
    "kinematics",
    "events",
    "comparison",
)

POSE2SIM_EXECUTION_STAGES: tuple[str, ...] = STAGES[1:8]
GENERAL_POSE2SIM_STAGES: tuple[str, ...] = STAGES[:8]

_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "calibration": (),
    "synchronization": ("calibration",),
    "poseEstimation": ("synchronization",),
    "personAssociation": ("poseEstimation",),
    "triangulation": ("personAssociation",),
    "filtering": ("triangulation",),
    "markerAugmentation": ("filtering",),
    "kinematics": ("markerAugmentation",),
    "events": ("kinematics",),
    "comparison": ("events",),
}

_CHANGE_RERUNS: dict[str, tuple[str, ...]] = {
    "calibration_change": STAGES,
    "synchronization_change": STAGES[1:],
    "2d_correction": STAGES[3:],
    "association_change": STAGES[4:],
    "filtering_change": STAGES[5:],
    "kinematics_change": STAGES[7:],
}


class StageGraph:
    def dependencies(self, stage: str) -> tuple[str, ...]:
        self._require_stage(stage)
        return _DEPENDENCIES[stage]

    def invalidate_from(
        self,
        stage: str,
        reason: str,
        operation_id: str | None = None,
    ) -> list[str]:
        self._require_stage(stage)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("invalidation reason must not be empty")
        if operation_id is not None and not operation_id.strip():
            raise ValueError("operation_id must not be empty when provided")
        downstream: dict[str, list[str]] = {name: [] for name in STAGES}
        for child, dependencies in _DEPENDENCIES.items():
            for dependency in dependencies:
                downstream[dependency].append(child)
        affected: list[str] = []
        queue: deque[str] = deque([stage])
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            affected.append(current)
            queue.extend(downstream[current])
        return [name for name in STAGES if name in affected]

    def rerun_stages_for(self, change: str) -> tuple[str, ...]:
        try:
            return _CHANGE_RERUNS[change]
        except KeyError as exc:
            raise ValueError(f"unknown change: {change}") from exc

    def executable_rerun_stages_for(self, change: str) -> tuple[str, ...]:
        affected = self.rerun_stages_for(change)
        return tuple(stage for stage in affected if stage in POSE2SIM_EXECUTION_STAGES)

    @staticmethod
    def _require_stage(stage: str) -> None:
        if stage not in _DEPENDENCIES:
            raise ValueError(f"unknown stage: {stage}")


def invalidate_manifest(
    manifest: dict[str, object],
    stage: str,
    reason: str,
    operation_ids: Iterable[str] = (),
) -> list[str]:
    operation_ids = tuple(operation_ids)
    affected = StageGraph().invalidate_from(
        stage, reason, operation_ids[0] if operation_ids else None
    )
    stages = manifest.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("project stages must be an object")
    for name in affected:
        record = stages.setdefault(name, {})
        if not isinstance(record, dict):
            raise ValueError(f"project stage must be an object: {name}")
        record["status"] = "stale"
        record["generation"] = int(record.get("generation", 0)) + 1
        record["invalidated_reason"] = reason
        if operation_ids:
            record["invalidated_by"] = list(operation_ids)
    return affected
