"""Tolerant, read-only trajectory readers used only by the 3D player."""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import c3d

from .model import PlaybackDiagnostic, PlaybackTrajectory, Point3D, TrajectorySource


_UNIT_ALIASES = {
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "centimeter": "cm",
    "centimeters": "cm",
    "millimeter": "mm",
    "millimeters": "mm",
}


def load_playback_trajectory(source: TrajectorySource) -> PlaybackTrajectory:
    if not source.path.is_file():
        raise FileNotFoundError(f"trajectory file not found: {source.path}")
    if source.format == "trc":
        return _load_trc(source)
    if source.format == "c3d":
        return _load_c3d(source)
    raise ValueError(f"unsupported trajectory format: {source.format}")


def _load_trc(source: TrajectorySource) -> PlaybackTrajectory:
    path = source.path
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 6:
        raise ValueError(f"TRC file is too short: {path}")
    data_rate: float | None = None
    declared_frames: int | None = None
    declared_markers: int | None = None
    unit: str | None = None
    for line in lines[:4]:
        fields = line.split("\t")
        if len(fields) < 5:
            continue
        try:
            data_rate = float(fields[0].strip())
            declared_frames = int(fields[2].strip())
            declared_markers = int(fields[3].strip())
        except ValueError:
            continue
        unit = _normalize_unit(fields[4])
        break
    if data_rate is None or data_rate <= 0 or unit is None:
        raise ValueError(f"TRC header does not declare valid data rate and units: {path}")
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("Frame#")),
        None,
    )
    if header_index is None or header_index + 2 >= len(lines):
        raise ValueError(f"TRC marker header is missing: {path}")
    header = lines[header_index].split("\t")
    labels = [header[index].strip() for index in range(2, len(header), 3) if header[index].strip()]
    if not labels:
        raise ValueError(f"TRC contains no marker labels: {path}")
    if declared_markers is not None and declared_markers != len(labels):
        raise ValueError(
            f"TRC declares {declared_markers} markers but header contains {len(labels)}: {path}"
        )
    frames: list[int] = []
    times: list[float] = []
    values: dict[str, list[Point3D]] = {label: [] for label in labels}
    required = 2 + len(labels) * 3
    for line_number, line in enumerate(lines[header_index + 2 :], start=header_index + 3):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < required:
            raise ValueError(
                f"TRC data row has {len(fields)} fields, expected {required}, line {line_number}: {path}"
            )
        try:
            frame = int(fields[0].strip())
            time_value = float(fields[1].strip())
        except ValueError as exc:
            raise ValueError(f"TRC frame/time is invalid at line {line_number}: {path}") from exc
        frames.append(frame)
        times.append(time_value)
        for marker_index, label in enumerate(labels):
            start = 2 + marker_index * 3
            try:
                point = tuple(
                    float(fields[start + offset]) if fields[start + offset].strip() else float("nan")
                    for offset in range(3)
                )
            except ValueError as exc:
                raise ValueError(
                    f"TRC coordinate is invalid for {label} at line {line_number}: {path}"
                ) from exc
            values[label].append(point)  # type: ignore[arg-type]
    diagnostics: list[PlaybackDiagnostic] = []
    if declared_frames is not None and declared_frames != len(frames):
        diagnostics.append(
            PlaybackDiagnostic(
                "frame_count_mismatch",
                f"TRC 声明 {declared_frames} 帧，实际读取 {len(frames)} 行；播放器按实际数据回放。",
            )
        )
    return PlaybackTrajectory(
        tuple(frames),
        tuple(times),
        {label: tuple(series) for label, series in values.items()},
        unit,
        source,
        tuple(diagnostics),
    )


def _load_c3d(source: TrajectorySource) -> PlaybackTrajectory:
    frames: list[int] = []
    times: list[float] = []
    values: dict[str, list[Point3D]]
    with source.path.open("rb") as handle:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"No analog data found in file\.",
                category=UserWarning,
                module=r"c3d(?:\.c3d)?",
            )
            reader = c3d.Reader(handle)
            labels = _unique_labels(reader.point_labels)
            values = {label: [] for label in labels}
            rate = float(reader.point_rate)
            if rate <= 0:
                raise ValueError(f"C3D point rate must be positive: {source.path}")
            unit_parameter = reader.get("POINT:UNITS")
            unit = _normalize_unit(
                unit_parameter.string_value if unit_parameter is not None else "mm"
            )
            first_frame: int | None = None
            for frame, points, _analog in reader.read_frames(copy=True, check_nan=False):
                frame = int(frame)
                if first_frame is None:
                    first_frame = frame
                frames.append(frame)
                times.append((frame - first_frame) / rate)
                for index, label in enumerate(labels):
                    row = points[index]
                    coordinates = tuple(float(value) for value in row[:3])
                    residual = float(row[3])
                    if residual < 0 or not all(
                        math.isfinite(value) for value in coordinates
                    ):
                        coordinates = (float("nan"), float("nan"), float("nan"))
                    values[label].append(coordinates)  # type: ignore[arg-type]
    return PlaybackTrajectory(
        tuple(frames),
        tuple(times),
        {label: tuple(series) for label, series in values.items()},
        unit,
        source,
        (
            PlaybackDiagnostic(
                "point_data_only",
                "播放器仅读取 C3D 三维点；模拟量、力台和事件数据不在本页显示。",
            ),
        ),
    )


def _normalize_unit(value: object) -> str:
    text = str(value).strip().casefold()
    normalized = _UNIT_ALIASES.get(text, text)
    if normalized not in {"m", "cm", "mm"}:
        raise ValueError(f"unsupported trajectory coordinate unit: {value}")
    return normalized


def _unique_labels(values: object) -> tuple[str, ...]:
    labels: list[str] = []
    for index, value in enumerate(values):
        label = str(value).strip() or f"point-{index + 1}"
        if label in labels:
            raise ValueError(f"C3D point label is duplicated: {label}")
        labels.append(label)
    if not labels:
        raise ValueError("C3D contains no point labels")
    return tuple(labels)
