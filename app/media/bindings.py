"""Manifest-only camera video binding operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.project.manager import ProjectManager

from .video_sources import CameraVideoSource, VideoSourceKind


@dataclass(frozen=True)
class DirectoryBindingResult:
    bound: tuple[CameraVideoSource, ...]
    unmatched_cameras: tuple[str, ...]
    ambiguous: dict[str, tuple[Path, ...]]
    unmatched_files: tuple[Path, ...]


class VideoBindingService:
    _FIELD_BY_KIND = {
        "original": "video_path",
        "pose2sim_overlay": "pose_video_path",
    }
    _VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
    _DERIVED_TOKENS = ("_pose", "_sync", "_tracked", "_calibration")

    @classmethod
    def bind(
        cls,
        project: ProjectManager,
        camera: str,
        path: Path,
        kind: VideoSourceKind,
        preferred: bool = True,
    ) -> CameraVideoSource:
        record = cls._camera_record(project, camera)
        field = cls._field(kind)
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"video file not found: {resolved}")
        record[field] = str(resolved)
        if preferred:
            record["preferred_video_kind"] = kind
        project.save_manifest()
        return CameraVideoSource(camera, resolved, kind)

    @classmethod
    def bind_directory(
        cls,
        project: ProjectManager,
        directory: Path,
        kind: VideoSourceKind = "original",
    ) -> DirectoryBindingResult:
        field = cls._field(kind)
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise FileNotFoundError(f"video directory not found: {directory}")
        files = tuple(
            sorted(
                (
                    path.resolve()
                    for path in directory.iterdir()
                    if path.is_file()
                    and path.suffix.casefold() in cls._VIDEO_SUFFIXES
                    and not (
                        kind == "original"
                        and any(token in path.stem.casefold() for token in cls._DERIVED_TOKENS)
                    )
                ),
                key=lambda path: path.name.casefold(),
            )
        )
        cameras = project.manifest.get("cameras", [])
        records = (
            [record for record in cameras if isinstance(record, dict)]
            if isinstance(cameras, list)
            else []
        )
        bound: list[CameraVideoSource] = []
        unmatched: list[str] = []
        ambiguous: dict[str, tuple[Path, ...]] = {}
        used: set[Path] = set()
        for record in records:
            camera = str(record.get("camera_id", "")).strip()
            if not camera:
                continue
            prefix = camera.casefold()
            matches = tuple(
                path
                for path in files
                if path.stem.casefold() == prefix
                or path.stem.casefold().startswith(
                    (f"{prefix}_", f"{prefix}-", f"{prefix} ")
                )
            )
            if len(matches) == 1:
                record[field] = str(matches[0])
                record["preferred_video_kind"] = kind
                source = CameraVideoSource(camera, matches[0], kind)
                bound.append(source)
                used.add(matches[0])
            elif not matches:
                unmatched.append(camera)
            else:
                ambiguous[camera] = matches
        if bound:
            project.save_manifest()
        return DirectoryBindingResult(
            tuple(bound),
            tuple(unmatched),
            ambiguous,
            tuple(path for path in files if path not in used),
        )

    @classmethod
    def clear(cls, project: ProjectManager, camera: str, kind: VideoSourceKind) -> None:
        record = cls._camera_record(project, camera)
        record.pop(cls._field(kind), None)
        if record.get("preferred_video_kind") == kind:
            other: VideoSourceKind = "pose2sim_overlay" if kind == "original" else "original"
            if record.get(cls._field(other)):
                record["preferred_video_kind"] = other
            else:
                record.pop("preferred_video_kind", None)
        project.save_manifest()

    @classmethod
    def set_preferred(
        cls, project: ProjectManager, camera: str, kind: VideoSourceKind
    ) -> None:
        record = cls._camera_record(project, camera)
        if not record.get(cls._field(kind)):
            raise ValueError(f"{camera} has no {kind} video binding")
        record["preferred_video_kind"] = kind
        project.save_manifest()

    @classmethod
    def _field(cls, kind: VideoSourceKind) -> str:
        try:
            return cls._FIELD_BY_KIND[kind]
        except KeyError as exc:
            raise ValueError(f"unknown video source kind: {kind}") from exc

    @staticmethod
    def _camera_record(project: ProjectManager, camera: str) -> dict[str, object]:
        cameras = project.manifest.get("cameras", [])
        if isinstance(cameras, list):
            for record in cameras:
                if isinstance(record, dict) and record.get("camera_id") == camera:
                    return record
        raise KeyError(f"camera not found: {camera}")
