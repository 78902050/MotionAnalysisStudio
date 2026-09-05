"""Normalized, validated camera calibration domain records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


def _finite_vector(value: object, length: int, field: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"calibration {field} must contain {length} values")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"calibration {field} must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"calibration {field} must contain finite values")
        result.append(number)
    return tuple(result)


@dataclass(frozen=True)
class CameraCalibration:
    camera: str
    image_size: tuple[int, int]
    matrix: tuple[tuple[float, float, float], ...]
    distortions: tuple[float, ...]
    rotation: tuple[float, float, float]
    translation: tuple[float, float, float]
    reprojection_error: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.camera, str) or not self.camera.strip():
            raise ValueError("calibration camera must not be empty")
        if (
            not isinstance(self.image_size, (list, tuple))
            or len(self.image_size) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in self.image_size)
        ):
            raise ValueError("calibration image_size must contain two positive integers")
        if not isinstance(self.matrix, (list, tuple)) or len(self.matrix) != 3:
            raise ValueError("calibration matrix must be 3x3")
        matrix = tuple(_finite_vector(row, 3, "matrix") for row in self.matrix)
        if matrix[0][0] <= 0 or matrix[1][1] <= 0:
            raise ValueError("calibration matrix focal lengths must be positive")
        if not (
            math.isclose(matrix[2][0], 0.0, abs_tol=1e-12)
            and math.isclose(matrix[2][1], 0.0, abs_tol=1e-12)
            and math.isclose(matrix[2][2], 1.0, abs_tol=1e-12)
        ):
            raise ValueError("calibration matrix must have homogeneous row [0, 0, 1]")
        if not isinstance(self.distortions, (list, tuple)):
            raise ValueError("calibration distortions must be an array")
        distortions = _finite_vector(self.distortions, len(self.distortions), "distortions")
        rotation = _finite_vector(self.rotation, 3, "rotation")
        translation = _finite_vector(self.translation, 3, "translation")
        error = self.reprojection_error
        if error is not None:
            if not isinstance(error, (int, float)) or isinstance(error, bool) or not math.isfinite(float(error)):
                raise ValueError("calibration reprojection_error must be finite")
            error = float(error)
        object.__setattr__(self, "image_size", tuple(self.image_size))
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "distortions", distortions)
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)
        object.__setattr__(self, "reprojection_error", error)


@dataclass(frozen=True)
class CalibrationSet:
    cameras: tuple[CameraCalibration, ...]
    source_format: str
    source_path: Path

    def __post_init__(self) -> None:
        cameras = tuple(self.cameras)
        if not cameras:
            raise ValueError(f"calibration has no cameras: {self.source_path}")
        names = tuple(camera.camera for camera in cameras)
        if len(set(names)) != len(names):
            raise ValueError(f"calibration camera names must be unique: {self.source_path}")
        if not isinstance(self.source_format, str) or not self.source_format:
            raise ValueError("calibration source_format must not be empty")
        object.__setattr__(self, "cameras", cameras)
        object.__setattr__(self, "source_path", Path(self.source_path))
