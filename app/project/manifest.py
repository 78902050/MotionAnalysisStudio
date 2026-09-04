"""Manifest defaults and project layout definitions."""

from datetime import datetime, timezone
from uuid import uuid4

STAGE_NAMES: tuple[str, ...] = (
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

DEFAULT_PATHS: dict[str, str] = {
    "config": "config/Config.toml",
    "quality_report": "reports/quality/current.json",
    "correction_root": "corrections",
    "logs": "logs",
}

PROJECT_DIRECTORIES: tuple[str, ...] = (
    "config",
    "calibration/source",
    "calibration/normalized",
    "calibration/reports",
    "pose",
    "pose-sync",
    "pose-associated",
    "pose-3d",
    "synchronization",
    "kinematics",
    "reports",
    "reports/quality",
    "reports/quality/history",
    "reports/metrics",
    "reports/comparisons",
    "corrections",
    "corrections/sessions",
    "corrections/backups/pose",
    "corrections/backups/association",
    "logs",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_project_manifest(name: str) -> dict[str, object]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("project name must not be empty")
    now = utc_now()
    return {
        "schema_version": 3,
        "project_id": f"project-{uuid4().hex[:12]}",
        "name": name,
        "created_at": now,
        "updated_at": now,
        "frame_base": 0,
        "people": [],
        "cameras": [],
        "stages": {
            stage: {"status": "not_started", "generation": 0} for stage in STAGE_NAMES
        },
        "paths": dict(DEFAULT_PATHS),
        "manual_pose_edits": [],
        "migration": {"source_schema_version": None, "migrated_at": None},
    }
