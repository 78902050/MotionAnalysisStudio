"""Project creation, opening, paths, and v2-to-v3 migration."""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import PROJECT_DIRECTORIES, new_project_manifest
from .migration import migrate_v2_manifest


def _atomic_text_replace(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@dataclass
class ProjectManager:
    root: Path
    manifest: dict[str, Any]
    migrated: bool = False

    @classmethod
    def create(cls, root: Path, name: str) -> "ProjectManager":
        root = Path(root)
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
        root = Path(root)
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

        self.manifest = migrate_v2_manifest(self.manifest)
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
        return self.root / Path(relative)

    def save_manifest(self) -> None:
        payload = json.dumps(self.manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        _atomic_text_replace(self.root / "manifest.json", payload)

    def _ensure_layout(self) -> None:
        for relative in PROJECT_DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / "corrections" / "history.jsonl").touch(exist_ok=True)
        config = self.root / "config" / "Config.toml"
        config.touch(exist_ok=True)
