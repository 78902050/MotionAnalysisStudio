"""Discover Pose2Sim result trials without requiring a project manifest."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .import_model import ArtifactSummary, ConfigState, TrialCandidate


_RESULT_DIRECTORIES = {"pose", "pose-sync", "pose-associated", "pose-3d", "kinematics"}
_DERIVED_VIDEO_TOKENS = ("_pose", "_sync", "_tracked", "_calibration")


class ExistingResultDiscovery:
    def discover_one(self, path: Path) -> TrialCandidate:
        root = Path(path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"已处理数据目录不存在：{root}")
        if not self._is_trial_root(root):
            raise ValueError(f"目录中未发现 Pose2Sim 已处理结果：{root}")

        cameras = self._camera_names(root)
        artifacts = ArtifactSummary(
            pose_2d=self._json_count(root / "pose"),
            pose_sync=self._json_count(root / "pose-sync"),
            pose_associated=self._json_count(root / "pose-associated"),
            trc=tuple(sorted(path.resolve() for path in (root / "pose-3d").glob("*.trc"))),
            kinematics=tuple(
                sorted(
                    path.resolve()
                    for suffix in ("*.mot", "*.sto")
                    for path in (root / "kinematics").glob(suffix)
                )
            ),
        )
        config_path, config_state = self._config(root)
        source_videos, derived_videos = self._videos(root)
        return TrialCandidate(
            root,
            cameras,
            artifacts,
            self._calibration(root),
            config_path,
            config_state,
            source_videos,
            derived_videos,
        )

    def scan(self, root: Path) -> tuple[TrialCandidate, ...]:
        root = Path(root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"扫描目录不存在：{root}")
        if self._is_trial_root(root):
            return (self.discover_one(root),)

        candidates: list[TrialCandidate] = []
        for current_text, directory_names, _file_names in os.walk(root):
            current = Path(current_text)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in _RESULT_DIRECTORIES
                and name not in {".git", ".venv", "corrections", "reports"}
            )
            if current == root or not self._is_trial_root(current):
                continue
            candidates.append(self.discover_one(current))
            directory_names[:] = []
        return tuple(sorted(candidates, key=lambda item: str(item.root).casefold()))

    @staticmethod
    def _is_trial_root(root: Path) -> bool:
        if any((root / name).is_dir() for name in _RESULT_DIRECTORIES):
            return True
        return any(root.glob("*.trc")) or any(root.glob("*.mot")) or any(root.glob("*.sto"))

    @staticmethod
    def _json_count(root: Path) -> int:
        if not root.is_dir():
            return 0
        return sum(1 for path in root.glob("*_json/*.json") if path.is_file()) + sum(
            1 for path in root.glob("*.json") if path.is_file()
        )

    @staticmethod
    def _camera_names(root: Path) -> tuple[str, ...]:
        names: set[str] = set()
        for layer in ("pose", "pose-sync", "pose-associated"):
            directory = root / layer
            if not directory.is_dir():
                continue
            names.update(
                child.name.removesuffix("_json")
                for child in directory.iterdir()
                if child.is_dir() and child.name.endswith("_json")
            )
        return tuple(sorted(names, key=str.casefold))

    @staticmethod
    def _calibration(root: Path) -> Path | None:
        for directory in (root, *tuple(root.parents)[:4]):
            for name in ("camera_array.toml", "camera_array_aniposelib.toml"):
                candidate = directory / name
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate.resolve()
        return None

    @staticmethod
    def _config(root: Path) -> tuple[Path | None, ConfigState]:
        candidates = (
            root / "config" / "Config.toml",
            root / "Config.toml",
            root / "config.toml",
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            return None, "missing"
        path = path.resolve()
        if path.stat().st_size == 0:
            return path, "empty"
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return path, "invalid"
        return path, "valid" if value else "empty"

    @staticmethod
    def _videos(root: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        source: list[Path] = []
        derived: list[Path] = []
        for path in sorted(root.rglob("*.mp4")):
            resolved = path.resolve()
            if any(token in path.stem.casefold() for token in _DERIVED_VIDEO_TOKENS):
                derived.append(resolved)
            else:
                source.append(resolved)
        return tuple(source), tuple(derived)

