"""Explicit semantic contracts for calculated metric series."""

from __future__ import annotations

from dataclasses import dataclass


_KINDS = {
    "position",
    "speed",
    "acceleration",
    "angle",
    "angular_velocity",
    "symmetry",
    "symmetry_legacy",
    "legacy",
}


@dataclass(frozen=True)
class MetricSeriesContract:
    metric_kind: str
    unit: str
    coordinate_unit: str
    coordinate_system: str
    algorithm_version: str
    time_base: str = "seconds"
    legacy: bool = False

    def __post_init__(self) -> None:
        if self.metric_kind not in _KINDS:
            raise ValueError(f"unsupported metric contract kind: {self.metric_kind}")
        for value, field in (
            (self.unit, "unit"),
            (self.coordinate_unit, "coordinate_unit"),
            (self.coordinate_system, "coordinate_system"),
            (self.algorithm_version, "algorithm_version"),
            (self.time_base, "time_base"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"metric contract {field} must not be empty")
        if self.time_base != "seconds":
            raise ValueError(f"unsupported metric time base: {self.time_base}")

    def compatibility_key(self) -> tuple[str, ...]:
        return (
            self.metric_kind,
            self.unit,
            self.coordinate_unit,
            self.coordinate_system,
            self.algorithm_version,
            self.time_base,
        )

    def compatible_with(self, other: "MetricSeriesContract") -> bool:
        return isinstance(other, MetricSeriesContract) and self.compatibility_key() == other.compatibility_key()

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_kind": self.metric_kind,
            "unit": self.unit,
            "coordinate_unit": self.coordinate_unit,
            "coordinate_system": self.coordinate_system,
            "algorithm_version": self.algorithm_version,
            "time_base": self.time_base,
            "legacy": self.legacy,
        }


def expected_unit(metric_kind: str, coordinate_unit: str) -> tuple[str, ...]:
    if metric_kind == "position":
        return (coordinate_unit,)
    if metric_kind == "speed":
        return (f"{coordinate_unit}/s",)
    if metric_kind == "acceleration":
        return (f"{coordinate_unit}/s^2",)
    if metric_kind == "angle":
        return ("deg", "rad")
    if metric_kind == "angular_velocity":
        return ("deg/s", "rad/s")
    if metric_kind in {"symmetry", "symmetry_legacy"}:
        return (coordinate_unit,)
    raise ValueError(f"unsupported metric kind: {metric_kind}")


def validate_metric_unit(metric_kind: str, unit: str, coordinate_unit: str) -> None:
    allowed = expected_unit(metric_kind, coordinate_unit)
    if unit not in allowed:
        raise ValueError(
            f"invalid unit for {metric_kind}: {unit}; expected {' or '.join(allowed)}"
        )
