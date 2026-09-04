"""Explicit coordinate metadata and unit conversion helpers."""

from __future__ import annotations

from collections.abc import Iterable

from .model import Point3D, SUPPORTED_UNITS


_TO_METERS = {"m": 1.0, "cm": 0.01, "mm": 0.001}


def unit_scale(source_unit: str, target_unit: str) -> float:
    if source_unit not in SUPPORTED_UNITS or target_unit not in SUPPORTED_UNITS:
        raise ValueError(f"unsupported coordinate unit conversion: {source_unit} -> {target_unit}")
    return _TO_METERS[source_unit] / _TO_METERS[target_unit]


def convert_points(points: Iterable[Point3D], source_unit: str, target_unit: str) -> tuple[Point3D, ...]:
    scale = unit_scale(source_unit, target_unit)
    result: list[Point3D] = []
    for point in points:
        if len(point) != 3:
            raise ValueError("each point must contain three coordinates")
        result.append(tuple(float(value) * scale for value in point))  # type: ignore[arg-type]
    return tuple(result)
