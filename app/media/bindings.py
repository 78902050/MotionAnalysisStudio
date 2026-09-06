"""Manifest-only camera video binding operations."""

from __future__ import annotations

from pathlib import Path

from app.project.manager import ProjectManager

from .video_sources import CameraVideoSource, VideoSourceKind


class VideoBindingService:
    _FIELD_BY_KIND = {
        "original": "video_path",
        "pose2sim_overlay": "pose_video_path",
    }

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
