"""Deterministic 3D-to-2D projection for the native trajectory canvas."""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Mapping

from PySide6.QtCore import QPointF

from .model import Point3D


@dataclass(frozen=True)
class ViewTransform:
    yaw: float = 0.0
    pitch: float = 0.0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    perspective: bool = False

    def __post_init__(self) -> None:
        values = (self.yaw, self.pitch, self.zoom, self.pan_x, self.pan_y)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("view transform values must be finite")
        if self.zoom <= 0:
            raise ValueError("view zoom must be positive")


FRONT_VIEW = ViewTransform()
SIDE_VIEW = ViewTransform(yaw=math.pi / 2)
TOP_VIEW = ViewTransform(pitch=math.pi / 2)


def view_coordinates(point: Point3D, transform: ViewTransform) -> Point3D | None:
    x, y, z = (float(value) for value in point)
    if not all(math.isfinite(value) for value in (x, y, z)):
        return None
    cosine_yaw = math.cos(transform.yaw)
    sine_yaw = math.sin(transform.yaw)
    yaw_x = cosine_yaw * x - sine_yaw * y
    yaw_y = sine_yaw * x + cosine_yaw * y
    cosine_pitch = math.cos(transform.pitch)
    sine_pitch = math.sin(transform.pitch)
    pitch_y = cosine_pitch * yaw_y - sine_pitch * z
    pitch_z = sine_pitch * yaw_y + cosine_pitch * z
    return yaw_x, pitch_y, pitch_z


def project_points(
    points: Mapping[str, Point3D],
    transform: ViewTransform,
    viewport: tuple[int, int],
) -> dict[str, QPointF | None]:
    width, height = viewport
    if width <= 0 or height <= 0:
        raise ValueError("viewport dimensions must be positive")
    center_x = width / 2 + transform.pan_x
    center_y = height / 2 + transform.pan_y
    projected: dict[str, QPointF | None] = {}
    for label, point in points.items():
        rotated = view_coordinates(point, transform)
        if rotated is None:
            projected[label] = None
            continue
        x, depth, vertical = rotated
        depth_scale = 1.0
        if transform.perspective:
            camera_distance = 1000.0
            depth_scale = camera_distance / max(camera_distance + depth, camera_distance * 0.1)
        scale = transform.zoom * depth_scale
        projected[label] = QPointF(center_x + x * scale, center_y - vertical * scale)
    return projected
