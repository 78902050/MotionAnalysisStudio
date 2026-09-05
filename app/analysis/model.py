"""Data contracts for traceable 3D trajectories and metric tables."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .contracts import MetricSeriesContract


Point3D = tuple[float, float, float]
PointSeries = tuple[Point3D, ...]

SUPPORTED_UNITS = {"m", "cm", "mm"}


def _as_point(value: object) -> Point3D:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("each trajectory point must contain three coordinates")
    result: list[float] = []
    for item in value:
        if item is None:
            result.append(float("nan"))
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            result.append(float(item))
        else:
            raise ValueError("trajectory coordinates must be numeric or None")
    return tuple(result)  # type: ignore[return-value]


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    unit: str
    required_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.metric_id, str) or not self.metric_id.strip():
            raise ValueError("metric_id must not be empty")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("metric unit must not be empty")
        labels = tuple(self.required_labels)
        if not labels or any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("required_labels must contain non-empty labels")
        object.__setattr__(self, "required_labels", labels)


@dataclass(frozen=True)
class MetricConfig:
    sampling_rate_hz: float
    coordinate_unit: str
    filter_name: str | None
    filter_window: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.sampling_rate_hz, (int, float)) or isinstance(self.sampling_rate_hz, bool):
            raise ValueError("sampling_rate_hz must be numeric")
        if not math.isfinite(float(self.sampling_rate_hz)) or float(self.sampling_rate_hz) <= 0:
            raise ValueError("sampling_rate_hz must be positive")
        if self.coordinate_unit not in SUPPORTED_UNITS:
            raise ValueError(f"unsupported coordinate unit: {self.coordinate_unit}")
        if self.filter_name not in {None, "moving_average", "median"}:
            raise ValueError(f"unsupported filter: {self.filter_name}")
        if not isinstance(self.filter_window, int) or isinstance(self.filter_window, bool) or self.filter_window < 1:
            raise ValueError("filter_window must be a positive integer")
        object.__setattr__(self, "sampling_rate_hz", float(self.sampling_rate_hz))


@dataclass(frozen=True)
class Trajectory:
    frames: tuple[int, ...]
    times: tuple[float, ...]
    points: Mapping[str, PointSeries]
    coordinate_unit: str
    coordinate_system: str
    source_path: str | None = None
    source_version: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        times = tuple(float(value) for value in self.times)
        if not frames:
            raise ValueError("trajectory must contain at least one frame")
        if len(frames) != len(times):
            raise ValueError("frames and times must have equal length")
        if any(not isinstance(frame, int) or isinstance(frame, bool) or frame < 0 for frame in frames):
            raise ValueError("trajectory frames must be non-negative integers")
        if any(not math.isfinite(time) for time in times):
            raise ValueError("trajectory times must be finite")
        if any(current <= previous for previous, current in zip(times, times[1:])):
            raise ValueError("trajectory times must be strictly increasing")
        if self.coordinate_unit not in SUPPORTED_UNITS:
            raise ValueError(f"unsupported coordinate unit: {self.coordinate_unit}")
        if not isinstance(self.coordinate_system, str) or not self.coordinate_system.strip():
            raise ValueError("coordinate_system must not be empty")

        normalized: dict[str, PointSeries] = {}
        for label, series in self.points.items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError("trajectory labels must be non-empty strings")
            values = tuple(_as_point(point) for point in series)
            if len(values) != len(frames):
                raise ValueError(f"trajectory label has wrong frame count: {label}")
            normalized[label] = values
        if not normalized:
            raise ValueError("trajectory must contain at least one label")
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "points", normalized)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.points)

    @classmethod
    def from_trc(cls, path: Path, coordinate_system: str) -> "Trajectory":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) < 6:
            raise ValueError(f"TRC file is too short: {path}")

        data_rate: float | None = None
        units: str | None = None
        declared_frames: int | None = None
        declared_markers: int | None = None
        for line in lines[:4]:
            fields = line.split("\t")
            if len(fields) >= 5 and fields[0].strip().replace(".", "", 1).isdigit():
                try:
                    data_rate = float(fields[0].strip())
                    declared_frames = int(fields[2].strip())
                    declared_markers = int(fields[3].strip())
                except (IndexError, ValueError) as exc:
                    raise ValueError(f"TRC header counts are invalid: {path}") from exc
                units = fields[4].strip() or None
                break
        if data_rate is None or units is None:
            raise ValueError(f"TRC header does not declare data rate and units: {path}")
        unit_aliases = {"meter": "m", "meters": "m", "metre": "m", "metres": "m", "centimeter": "cm", "millimeter": "mm"}
        units = unit_aliases.get(units.lower(), units.lower())
        if units not in SUPPORTED_UNITS:
            raise ValueError(f"unsupported TRC coordinate unit: {units}")

        header_index = next((index for index, line in enumerate(lines) if line.strip().startswith("Frame#")), None)
        if header_index is None or header_index + 2 >= len(lines):
            raise ValueError(f"TRC marker header is missing: {path}")
        header = lines[header_index].split("\t")
        labels: list[str] = []
        for index in range(2, len(header), 3):
            label = header[index].strip()
            if label:
                labels.append(label)
        if not labels:
            raise ValueError(f"TRC contains no marker labels: {path}")
        if declared_markers is not None and len(labels) != declared_markers:
            raise ValueError(
                f"TRC declares {declared_markers} markers but header contains {len(labels)}: {path}"
            )

        frames: list[int] = []
        times: list[float] = []
        values: dict[str, list[Point3D]] = {label: [] for label in labels}
        for line_number, line in enumerate(lines[header_index + 2 :], start=header_index + 3):
            if not line.strip():
                continue
            fields = line.split("\t")
            required_fields = 2 + len(labels) * 3
            if len(fields) < required_fields:
                raise ValueError(
                    f"TRC data row has {len(fields)} fields, expected at least {required_fields}, line {line_number}: {path}"
                )
            try:
                frame = int(fields[0].strip())
                time = float(fields[1].strip())
            except (IndexError, ValueError) as exc:
                raise ValueError(f"TRC frame/time is invalid at line {line_number}: {path}") from exc
            frames.append(frame)
            times.append(time)
            for marker_index, label in enumerate(labels):
                start = 2 + marker_index * 3
                coords: list[float] = []
                for offset in range(3):
                    try:
                        raw = fields[start + offset].strip()
                        coords.append(float(raw) if raw else float("nan"))
                    except (IndexError, ValueError) as exc:
                        raise ValueError(
                            f"TRC coordinate is invalid for {label} at line {line_number}: {path}"
                        ) from exc
                values[label].append(tuple(coords))  # type: ignore[arg-type]
        if not frames:
            raise ValueError(f"TRC contains no data rows: {path}")
        if declared_frames is not None and len(frames) != declared_frames:
            raise ValueError(
                f"TRC declares {declared_frames} frames but contains {len(frames)} data rows: {path}"
            )
        return cls(
            tuple(frames),
            tuple(times),
            {label: tuple(series) for label, series in values.items()},
            units,
            coordinate_system,
            str(path),
            f"TRC DataRate={data_rate:g}; Units={units}",
            {"sampling_rate_hz": data_rate, "format": "TRC"},
        )


@dataclass(frozen=True)
class MetricTable:
    frames: tuple[int, ...]
    times: tuple[float, ...]
    columns: Mapping[str, tuple[float, ...]]
    units: Mapping[str, str]
    metadata: Mapping[str, object]
    provenance: Mapping[str, Mapping[str, object]]
    contracts: Mapping[str, MetricSeriesContract] = field(default_factory=dict)

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        times = tuple(float(value) for value in self.times)
        if len(frames) != len(times):
            raise ValueError("metric table frames and times must have equal length")
        columns: dict[str, tuple[float, ...]] = {}
        for name, values in self.columns.items():
            normalized = tuple(float(value) for value in values)
            if len(normalized) != len(frames):
                raise ValueError(f"metric column has wrong frame count: {name}")
            columns[name] = normalized
        if set(columns) != set(self.units):
            raise ValueError("metric columns and units must have the same keys")
        if set(columns) != set(self.provenance):
            raise ValueError("metric columns and provenance must have the same keys")
        contracts = dict(self.contracts)
        if contracts and set(columns) != set(contracts):
            raise ValueError("metric columns and contracts must have the same keys")
        if not contracts:
            coordinate_unit = str(self.metadata.get("coordinate_unit", "unknown"))
            coordinate_system = str(self.metadata.get("coordinate_system", "unknown"))
            contracts = {
                name: MetricSeriesContract(
                    "legacy",
                    str(self.units[name]),
                    coordinate_unit,
                    coordinate_system,
                    "legacy",
                    legacy=True,
                )
                for name in columns
            }
        if any(not isinstance(contract, MetricSeriesContract) for contract in contracts.values()):
            raise TypeError("metric contracts must contain MetricSeriesContract values")
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "units", dict(self.units))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "provenance", {key: dict(value) for key, value in self.provenance.items()})
        object.__setattr__(self, "contracts", contracts)

    def column(self, name: str) -> tuple[float, ...]:
        try:
            return self.columns[name]
        except KeyError as exc:
            raise KeyError(f"unknown metric column: {name}") from exc

    def contract(self, name: str) -> MetricSeriesContract:
        try:
            return self.contracts[name]
        except KeyError as exc:
            raise KeyError(f"unknown metric contract: {name}") from exc

    def to_dict(self) -> dict[str, object]:
        def json_value(value: object) -> object:
            if isinstance(value, float) and math.isnan(value):
                return None
            if isinstance(value, tuple):
                return [json_value(item) for item in value]
            if isinstance(value, dict):
                return {str(key): json_value(item) for key, item in value.items()}
            return value

        return {
            "frames": list(self.frames),
            "times": list(self.times),
            "columns": {name: [json_value(value) for value in values] for name, values in self.columns.items()},
            "units": dict(self.units),
            "metadata": json_value(dict(self.metadata)),
            "provenance": json_value({name: dict(value) for name, value in self.provenance.items()}),
            "contracts": {name: contract.to_dict() for name, contract in self.contracts.items()},
        }
