"""Configurable, gap-aware kinematic metric calculation."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .contracts import MetricSeriesContract, validate_metric_unit
from .coordinates import convert_points
from .filters import filter_values
from .model import MetricConfig, MetricDefinition, MetricTable, Point3D, Trajectory


NAN = float("nan")


def finite_difference(values: Sequence[float], times: Sequence[float]) -> tuple[float, ...]:
    """Differentiate each contiguous finite run using one-sided edge differences."""
    if len(values) != len(times):
        raise ValueError("values and times must have equal length")
    result = [NAN] * len(values)
    for start, end in _finite_segments(values):
        if end - start < 2:
            continue
        for index in range(start, end):
            if index == start:
                left, right = index, index + 1
            elif index == end - 1:
                left, right = index - 1, index
            else:
                left, right = index - 1, index + 1
            delta_time = float(times[right]) - float(times[left])
            if delta_time <= 0:
                raise ValueError("times must be strictly increasing")
            result[index] = (float(values[right]) - float(values[left])) / delta_time
    return tuple(result)


class MetricEngine:
    def calculate(
        self,
        trajectory: Trajectory,
        definitions: Sequence[MetricDefinition],
        config: MetricConfig,
    ) -> MetricTable:
        if not definitions:
            raise ValueError("at least one metric definition is required")
        self._validate_timeline(trajectory, config)
        points = self._prepare_points(trajectory, config)
        columns: dict[str, tuple[float, ...]] = {}
        units: dict[str, str] = {}
        provenance: dict[str, dict[str, object]] = {}
        contracts: dict[str, MetricSeriesContract] = {}
        for definition in definitions:
            kind, labels = self._parse_definition(definition)
            validate_metric_unit(kind, definition.unit, config.coordinate_unit)
            missing_labels = tuple(label for label in labels if label not in points)
            metric_values = self._calculate_metric(kind, labels, points, trajectory.times, definition.unit)
            output_values = self._metric_columns(kind, labels, metric_values)
            for column_name, values in output_values.items():
                if column_name in columns:
                    raise ValueError(f"duplicate metric column: {column_name}")
                columns[column_name] = values
                units[column_name] = definition.unit
                provenance[column_name] = {
                    "metric_id": definition.metric_id,
                    "input_labels": labels,
                    "missing_labels": missing_labels,
                    "input_source": trajectory.source_path,
                    "input_version": trajectory.source_version,
                    "coordinate_unit": config.coordinate_unit,
                    "coordinate_system": trajectory.coordinate_system,
                    "sampling_rate_hz": config.sampling_rate_hz,
                    "filter_name": config.filter_name,
                    "filter_window": config.filter_window,
                    "algorithm_version": "kinematics-v2",
                }
                contracts[column_name] = MetricSeriesContract(
                    kind,
                    definition.unit,
                    config.coordinate_unit,
                    trajectory.coordinate_system,
                    "kinematics-v2",
                )
        metadata = {
            "coordinate_unit": config.coordinate_unit,
            "coordinate_system": trajectory.coordinate_system,
            "sampling_rate_hz": config.sampling_rate_hz,
            "filter_name": config.filter_name,
            "filter_window": config.filter_window,
            "input_source": trajectory.source_path,
            "input_version": trajectory.source_version,
            "metric_ids": tuple(definition.metric_id for definition in definitions),
        }
        return MetricTable(trajectory.frames, trajectory.times, columns, units, metadata, provenance, contracts)

    @staticmethod
    def _validate_timeline(trajectory: Trajectory, config: MetricConfig) -> None:
        metadata_rate = trajectory.metadata.get("sampling_rate_hz")
        if isinstance(metadata_rate, (int, float)) and not isinstance(metadata_rate, bool):
            if not math.isclose(float(metadata_rate), config.sampling_rate_hz, rel_tol=1e-6, abs_tol=1e-9):
                raise ValueError(
                    "sampling rate metadata does not match calculation configuration"
                )
        for index, (previous_time, current_time) in enumerate(zip(trajectory.times, trajectory.times[1:]), start=1):
            frame_delta = trajectory.frames[index] - trajectory.frames[index - 1]
            if frame_delta <= 0:
                raise ValueError("trajectory frames must be strictly increasing for timeline validation")
            expected = frame_delta / config.sampling_rate_hz
            actual = current_time - previous_time
            if not math.isclose(actual, expected, rel_tol=1e-3, abs_tol=1e-6):
                raise ValueError(
                    f"sampling rate does not match timeline at frame {trajectory.frames[index]}: "
                    f"expected {expected:.9g}s, got {actual:.9g}s"
                )

    @staticmethod
    def _prepare_points(trajectory: Trajectory, config: MetricConfig) -> dict[str, tuple[Point3D, ...]]:
        result: dict[str, tuple[Point3D, ...]] = {}
        for label, series in trajectory.points.items():
            converted = convert_points(series, trajectory.coordinate_unit, config.coordinate_unit)
            if config.filter_name is None:
                result[label] = converted
                continue
            valid = [_valid_point(point) for point in converted]
            components: list[tuple[float, ...]] = []
            for axis in range(3):
                values = tuple(point[axis] if valid[index] else NAN for index, point in enumerate(converted))
                components.append(filter_values(values, config.filter_name, window=config.filter_window))
            result[label] = tuple(
                (components[0][index], components[1][index], components[2][index])
                if valid[index]
                else (NAN, NAN, NAN)
                for index in range(len(converted))
            )
        return result

    @staticmethod
    def _parse_definition(definition: MetricDefinition) -> tuple[str, tuple[str, ...]]:
        parts = definition.metric_id.split(":")
        kind = parts[0].strip().lower()
        if kind not in {"position", "speed", "acceleration", "angle", "angular_velocity", "symmetry", "symmetry_legacy"}:
            raise ValueError(f"unsupported metric: {definition.metric_id}")
        labels = tuple(part.strip() for part in parts[1:] if part.strip()) or tuple(definition.required_labels)
        expected = {
            "position": 1,
            "speed": 1,
            "acceleration": 1,
            "angle": 3,
            "angular_velocity": 3,
            "symmetry": 3,
            "symmetry_legacy": 2,
        }[kind]
        if len(labels) != expected or tuple(definition.required_labels) != labels:
            raise ValueError(f"metric labels do not match definition: {definition.metric_id}")
        return kind, labels

    @staticmethod
    def _calculate_metric(
        kind: str,
        labels: tuple[str, ...],
        points: dict[str, tuple[Point3D, ...]],
        times: tuple[float, ...],
        unit: str,
    ) -> object:
        if kind == "position":
            return points.get(labels[0], _missing_points(len(times)))
        if kind == "speed":
            point_values = points.get(labels[0], _missing_points(len(times)))
            velocity = _vector_difference(point_values, times)
            return tuple(_norm(point) if _valid_point(point) else NAN for point in velocity)
        if kind == "acceleration":
            point_values = points.get(labels[0], _missing_points(len(times)))
            velocity = _vector_difference(point_values, times)
            acceleration = _vector_difference(velocity, times)
            return tuple(_norm(point) if _valid_point(point) else NAN for point in acceleration)
        if kind in {"angle", "angular_velocity"}:
            angle = _angles(
                points.get(labels[0], _missing_points(len(times))),
                points.get(labels[1], _missing_points(len(times))),
                points.get(labels[2], _missing_points(len(times))),
                unit,
            )
            return finite_difference(angle, times) if kind == "angular_velocity" else angle
        left = points.get(labels[0], _missing_points(len(times)))
        right = points.get(labels[1], _missing_points(len(times)))
        if kind == "symmetry_legacy":
            return tuple(abs(_norm(a) - _norm(b)) if _valid_point(a) and _valid_point(b) else NAN for a, b in zip(left, right))
        midline = points.get(labels[2], _missing_points(len(times)))
        return tuple(
            abs(_distance(a, center) - _distance(b, center))
            if _valid_point(a) and _valid_point(b) and _valid_point(center)
            else NAN
            for a, b, center in zip(left, right, midline)
        )

    @staticmethod
    def _metric_columns(kind: str, labels: tuple[str, ...], values: object) -> dict[str, tuple[float, ...]]:
        if kind == "position":
            points = values
            assert isinstance(points, tuple)
            return {
                f"{labels[0]}.x": tuple(point[0] for point in points),
                f"{labels[0]}.y": tuple(point[1] for point in points),
                f"{labels[0]}.z": tuple(point[2] for point in points),
            }
        if kind == "speed":
            return {f"{labels[0]}.speed": values}  # type: ignore[dict-item]
        if kind == "acceleration":
            return {f"{labels[0]}.acceleration": values}  # type: ignore[dict-item]
        if kind == "angle":
            return {f"angle.{'.'.join(labels)}": values}  # type: ignore[dict-item]
        if kind == "angular_velocity":
            return {f"angular_velocity.{'.'.join(labels)}": values}  # type: ignore[dict-item]
        if kind == "symmetry_legacy":
            return {f"symmetry_legacy.{'.'.join(labels)}": values}  # type: ignore[dict-item]
        return {f"symmetry.{'.'.join(labels)}": values}  # type: ignore[dict-item]


def _vector_difference(points: tuple[Point3D, ...], times: tuple[float, ...]) -> tuple[Point3D, ...]:
    result = [_missing_point() for _ in points]
    for start, end in _finite_point_segments(points):
        segment = points[start:end]
        for axis in range(3):
            values = tuple(point[axis] for point in segment)
            differences = finite_difference(values, times[start:end])
            for offset, _value in enumerate(differences):
                result[start + offset] = tuple(
                    differences[offset] if axis_index == axis else result[start + offset][axis_index]
                    for axis_index in range(3)
                )
    return tuple(result)


def _angles(
    first: tuple[Point3D, ...],
    middle: tuple[Point3D, ...],
    last: tuple[Point3D, ...],
    unit: str,
) -> tuple[float, ...]:
    result: list[float] = []
    radians = unit.lower().startswith("rad")
    for point_a, point_b, point_c in zip(first, middle, last):
        if not (_valid_point(point_a) and _valid_point(point_b) and _valid_point(point_c)):
            result.append(NAN)
            continue
        vector_a = tuple(point_a[index] - point_b[index] for index in range(3))
        vector_c = tuple(point_c[index] - point_b[index] for index in range(3))
        norm_a, norm_c = _norm(vector_a), _norm(vector_c)
        if norm_a == 0 or norm_c == 0:
            result.append(NAN)
            continue
        cosine = max(-1.0, min(1.0, sum(vector_a[index] * vector_c[index] for index in range(3)) / (norm_a * norm_c)))
        angle = math.acos(cosine)
        result.append(angle if radians else math.degrees(angle))
    return tuple(result)


def _finite_segments(values: Sequence[float]) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if math.isfinite(float(value)):
            if start is None:
                start = index
        elif start is not None:
            segments.append((start, index))
            start = None
    if start is not None:
        segments.append((start, len(values)))
    return tuple(segments)


def _finite_point_segments(points: Sequence[Point3D]) -> tuple[tuple[int, int], ...]:
    return _finite_segments(tuple(1.0 if _valid_point(point) else NAN for point in points))


def _missing_point() -> Point3D:
    return (NAN, NAN, NAN)


def _missing_points(count: int) -> tuple[Point3D, ...]:
    return tuple(_missing_point() for _ in range(count))


def _valid_point(point: Point3D) -> bool:
    return all(math.isfinite(float(value)) for value in point)


def _norm(point: Point3D) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in point))


def _distance(first: Point3D, second: Point3D) -> float:
    return _norm(tuple(first[index] - second[index] for index in range(3)))
