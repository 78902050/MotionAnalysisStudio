"""Project creation, opening, paths, and v2-to-v3 migration."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.io.atomic import AtomicJsonStore
from app.pipeline.dependency_graph import invalidate_manifest

from .manifest import PROJECT_DIRECTORIES, new_project_manifest
from .manifest import utc_now
from .migration import migrate_v2_manifest


class ProjectPathError(ValueError):
    """A manifest path points outside its owning project."""


@dataclass
class ProjectManager:
    root: Path
    manifest: dict[str, Any]
    migrated: bool = False

    @classmethod
    def create(cls, root: Path, name: str) -> "ProjectManager":
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(f"project manifest already exists: {manifest_path}")

        manifest = new_project_manifest(name)
        manager = cls(root=root, manifest=manifest, migrated=False)
        manager._ensure_layout()
        manager.save_manifest()
        return manager

    @classmethod
    def open(cls, root: Path) -> "ProjectManager":
        root = Path(root).resolve()
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"project manifest not found: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid project manifest: {manifest_path}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("project manifest must contain a JSON object")

        manager = cls(root=root, manifest=manifest)
        manager.migrate_if_needed()
        manager._ensure_layout()
        return manager

    def migrate_if_needed(self) -> bool:
        version = self.manifest.get("schema_version", 2)
        if version == 3:
            return False
        if version != 2:
            raise ValueError(f"unsupported project schema version: {version}")

        original_text = (self.root / "manifest.json").read_text(encoding="utf-8")
        backup_dir = self.root / "migration" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "manifest-v2.json"
        if not backup_path.exists():
            with backup_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(original_text)
                handle.flush()
                os.fsync(handle.fileno())

        self.manifest = migrate_v2_manifest(
            self.manifest, project_identity=str(self.root.resolve())
        )
        self._ensure_layout()
        self.save_manifest()
        self.migrated = True
        return True

    def path_for(self, key: str) -> Path:
        try:
            relative = self.manifest["paths"][key]
        except KeyError as exc:
            raise KeyError(f"unknown manifest path: {key}") from exc
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"manifest path must be a non-empty string: {key}")
        relative_path = Path(relative)
        if relative_path.is_absolute():
            raise ProjectPathError(f"manifest path must be relative to the project: {key}")
        root = self.root.resolve()
        resolved = (root / relative_path).resolve()
        if not resolved.is_relative_to(root):
            raise ProjectPathError(f"manifest path escapes the project root: {key}")
        return resolved

    def save_manifest(self) -> None:
        AtomicJsonStore.replace(self.root / "manifest.json", self.manifest)

    def invalidate_from(
        self,
        stage: str,
        reason: str,
        operation_ids: tuple[str, ...] | list[str] = (),
    ) -> list[str]:
        affected = invalidate_manifest(self.manifest, stage, reason, operation_ids)
        self.manifest["updated_at"] = utc_now()
        self.save_manifest()
        return affected

    def _ensure_layout(self) -> None:
        for relative in PROJECT_DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / "corrections" / "history.jsonl").touch(exist_ok=True)
        config = self.root / "config" / "Config.toml"
        config.touch(exist_ok=True)
