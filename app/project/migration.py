"""Idempotent migration from the legacy project manifest format."""

from copy import deepcopy

from .manifest import DEFAULT_PATHS, STAGE_NAMES, utc_now


def migrate_v2_manifest(manifest: dict[str, object]) -> dict[str, object]:
    """Return a v3 manifest while preserving all legacy user-owned values."""

    migrated = deepcopy(manifest)
    original_version = migrated.get("schema_version", 2)
    if original_version != 2:
        raise ValueError(f"cannot migrate schema version {original_version}")

    migrated["schema_version"] = 3
    migrated.setdefault("project_id", f"project-migrated-{id(manifest):x}")
    migrated.setdefault("created_at", utc_now())
    migrated["updated_at"] = utc_now()
    migrated.setdefault("frame_base", 0)
    migrated.setdefault("people", [])
    migrated.setdefault("cameras", [])
    migrated.setdefault("manual_pose_edits", [])

    old_paths = migrated.get("paths")
    paths = dict(DEFAULT_PATHS)
    if isinstance(old_paths, dict):
        paths.update(old_paths)
    migrated["paths"] = paths

    old_stages = migrated.get("stages")
    stages = {
        stage: {"status": "not_started", "generation": 0} for stage in STAGE_NAMES
    }
    if isinstance(old_stages, dict):
        for stage, record in old_stages.items():
            if isinstance(record, dict):
                stages[stage] = dict(record)
    migrated["stages"] = stages
    migrated["migration"] = {
        "source_schema_version": 2,
        "migrated_at": utc_now(),
    }
    return migrated
