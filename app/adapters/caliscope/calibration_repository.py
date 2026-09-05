"""Adapters from Caliscope/aniposelib exports to normalized calibration records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.calibration import CalibrationSet, CameraCalibration

from .reader import CaliscopeReader


class CaliscopeCalibrationRepository:
    def load(self, path: Path) -> CalibrationSet:
        path = Path(path)
        value = CaliscopeReader(path).read()
        if isinstance(value.get("cameras"), dict):
            entries = value["cameras"].items()
            cameras = tuple(self._camera(item, str(key), "caliscope_toml") for key, item in entries)
            source_format = "caliscope_toml"
        elif path.suffix.lower() == ".toml" and any(
            key.startswith("cam_") and isinstance(item, dict) for key, item in value.items()
        ):
            entries = (
                (key, item)
                for key, item in value.items()
                if key.startswith("cam_") and isinstance(item, dict)
            )
            cameras = tuple(self._camera(item, str(key), "aniposelib_toml") for key, item in entries)
            source_format = "aniposelib_toml"
        elif isinstance(value.get("cameras"), list):
            cameras = tuple(
                self._legacy_json_camera(item)
                for item in value["cameras"]
                if isinstance(item, dict)
            )
            source_format = "legacy_json"
        else:
            cameras = ()
            source_format = "caliscope_toml" if path.suffix.lower() == ".toml" else "legacy_json"
        return CalibrationSet(cameras, source_format, path)

    @staticmethod
    def _camera(item: object, fallback_name: str, source_format: str) -> CameraCalibration:
        if not isinstance(item, dict):
            raise ValueError(f"{source_format} camera entry must be a table")
        if source_format == "caliscope_toml":
            camera = str(item.get("cam_id", fallback_name))
        else:
            camera = str(item.get("name", fallback_name))
        return CameraCalibration(
            camera=camera,
            image_size=item.get("size"),
            matrix=item.get("matrix"),
            distortions=item.get("distortions", ()),
            rotation=item.get("rotation"),
            translation=item.get("translation"),
            reprojection_error=item.get("error"),
        )

    @staticmethod
    def _legacy_json_camera(item: dict[str, Any]) -> CameraCalibration:
        camera = item.get("camera_id")
        if not isinstance(camera, str) or not camera.strip():
            raise ValueError("legacy calibration camera has no camera_id")
        intrinsics = item.get("intrinsics") if isinstance(item.get("intrinsics"), dict) else {}
        extrinsics = item.get("extrinsics") if isinstance(item.get("extrinsics"), dict) else {}
        matrix = item.get("matrix")
        if matrix is None:
            fx = intrinsics.get("fx", 1.0)
            fy = intrinsics.get("fy", 1.0)
            cx = intrinsics.get("cx", 0.0)
            cy = intrinsics.get("cy", 0.0)
            matrix = ((fx, 0.0, cx), (0.0, fy, cy), (0.0, 0.0, 1.0))
        return CameraCalibration(
            camera=camera,
            image_size=tuple(item.get("size", (1, 1))),
            matrix=matrix,
            distortions=tuple(item.get("distortions", ())),
            rotation=item.get("rotation", extrinsics.get("rotation", (0.0, 0.0, 0.0))),
            translation=item.get("translation", extrinsics.get("translation", (0.0, 0.0, 0.0))),
            reprojection_error=item.get("reprojection_error"),
        )
