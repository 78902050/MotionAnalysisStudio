"""Idempotent migration from the legacy project manifest format."""

import json
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from .manifest import DEFAULT_PATHS, STAGE_NAMES, utc_now


def migrate_v2_manifest(
    manifest: dict[str, object], *, project_identity: str | None = None
) -> dict[str, object]:
    """Return a v3 manifest while preserving all legacy user-owned values."""

    migrated = deepcopy(manifest)
    original_version = migrated.get("schema_version", 2)
    if original_version != 2:
        raise ValueError(f"cannot migrate schema version {original_version}")

    migrated["schema_version"] = 3
    if "project_id" not in migrated:
        identity = project_identity or json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        migrated["project_id"] = f"project-migrated-{uuid5(NAMESPACE_URL, identity).hex[:12]}"
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
