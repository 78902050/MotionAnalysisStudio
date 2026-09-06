"""Resolve per-camera video sources without modifying media files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.project.manager import ProjectManager


VideoSourceKind = Literal["original", "pose2sim_overlay"]


@dataclass(frozen=True)
class CameraVideoSource:
    camera: str
    path: Path
    kind: VideoSourceKind

    def __post_init__(self) -> None:
        camera = self.camera.strip()
        if not camera:
            raise ValueError("camera must not be empty")
        if self.kind not in {"original", "pose2sim_overlay"}:
            raise ValueError(f"unknown video source kind: {self.kind}")
        object.__setattr__(self, "camera", camera)
        object.__setattr__(self, "path", Path(self.path).resolve())

    @property
    def display_kind(self) -> str:
        return "原视频" if self.kind == "original" else "Pose2Sim 二维标记视频"


class VideoSourceResolver:
    """Choose one readable source for each camera in a project manifest."""

    @classmethod
    def resolve(cls, project: ProjectManager) -> dict[str, CameraVideoSource]:
        resolved: dict[str, CameraVideoSource] = {}
        cameras = project.manifest.get("cameras", [])
        if not isinstance(cameras, list):
            return resolved
        for record in cameras:
            if not isinstance(record, dict):
                continue
            camera = str(record.get("camera_id", "")).strip()
            if not camera:
                continue
            candidates = {
                "original": cls._readable_path(project, record.get("video_path")),
                "pose2sim_overlay": cls._readable_path(project, record.get("pose_video_path")),
            }
            preferred = record.get("preferred_video_kind")
            order: tuple[VideoSourceKind, VideoSourceKind]
            if preferred == "pose2sim_overlay":
                order = ("pose2sim_overlay", "original")
            else:
                order = ("original", "pose2sim_overlay")
            for kind in order:
                path = candidates[kind]
                if path is not None:
                    resolved[camera] = CameraVideoSource(camera, path, kind)
                    break
        return resolved

    @staticmethod
    def _readable_path(project: ProjectManager, value: object) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        path = Path(value)
        if not path.is_absolute():
            path = project.root / path
        path = path.resolve()
        return path if path.is_file() else None
