"""Deterministic threshold events over traceable metric tables."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .model import MetricTable


EventOperator = Literal["crosses_above", "crosses_below", "above", "below"]
EventRole = Literal["start", "end", "point"]


@dataclass(frozen=True)
class EventRule:
    rule_id: str
    column: str
    operator: EventOperator
    threshold: float
    name: str = ""
    role: EventRole = "point"

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("event rule id must not be empty")
        if not self.column.strip():
            raise ValueError("event rule column must not be empty")
        if self.operator not in {"crosses_above", "crosses_below", "above", "below"}:
            raise ValueError(f"unsupported event operator: {self.operator}")
        if not isinstance(self.threshold, (int, float)) or isinstance(self.threshold, bool):
            raise ValueError("event threshold must be numeric")
        if not math.isfinite(float(self.threshold)):
            raise ValueError("event threshold must be finite")
        if self.role not in {"start", "end", "point"}:
            raise ValueError(f"unsupported event role: {self.role}")
        object.__setattr__(self, "threshold", float(self.threshold))


@dataclass(frozen=True)
class Event:
    event_id: str
    rule_id: str
    role: EventRole
    frame: int
    time: float
    value: float
    segment_id: str
    source: str = "detected"
    note: str = ""
    detector_version: str = "event-detector-v1"

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.rule_id.strip():
            raise ValueError("event id and rule id must not be empty")
        if not isinstance(self.frame, int) or isinstance(self.frame, bool) or self.frame < 0:
            raise ValueError("event frame must be a non-negative integer")
        if not math.isfinite(float(self.time)) or not math.isfinite(float(self.value)):
            raise ValueError("event time and value must be finite")
        if not self.segment_id.strip():
            raise ValueError("event segment id must not be empty")
        if self.role not in {"start", "end", "point"}:
            raise ValueError(f"unsupported event role: {self.role}")
        if not self.source.strip():
            raise ValueError("event source must not be empty")
        if not self.detector_version.strip():
            raise ValueError("event detector_version must not be empty")
        object.__setattr__(self, "time", float(self.time))
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "rule_id": self.rule_id,
            "role": self.role,
            "frame": self.frame,
            "time": self.time,
            "value": self.value,
            "segment_id": self.segment_id,
            "source": self.source,
            "note": self.note,
            "detector_version": self.detector_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Event":
        return cls(
            str(value["event_id"]),
            str(value["rule_id"]),
            value["role"],  # type: ignore[arg-type]
            int(value["frame"]),
            float(value["time"]),
            float(value["value"]),
            str(value["segment_id"]),
            str(value.get("source", "detected")),
            str(value.get("note", "")),
            str(value.get("detector_version", "event-detector-v1")),
        )


class EventDetector:
    """Detect threshold-entry events without crossing missing data."""

    def __init__(self, version: str = "event-detector-v1") -> None:
        if not isinstance(version, str) or not version.strip():
            raise ValueError("event detector version must not be empty")
        self.version = version

    def detect(self, metrics: MetricTable, rule: EventRule) -> tuple[Event, ...]:
        values = metrics.column(rule.column)
        events: list[Event] = []
        index = 0
        while index < len(values):
            if not math.isfinite(values[index]):
                index += 1
                continue
            start = index
            while index + 1 < len(values):
                next_value = values[index + 1]
                adjacent = metrics.frames[index + 1] == metrics.frames[index] + 1
                if not math.isfinite(next_value) or not adjacent:
                    break
                index += 1
            end = index
            segment_id = f"segment-{metrics.frames[start]}"
            occurrence = 0
            for current in range(start + 1, end + 1):
                previous_value = values[current - 1]
                current_value = values[current]
                if self._is_entry(previous_value, current_value, rule):
                    frame = metrics.frames[current]
                    events.append(
                        Event(
                            f"event-{rule.rule_id}-{segment_id}-{occurrence}",
                            rule.rule_id,
                            rule.role,
                            frame,
                            metrics.times[current],
                            current_value,
                            segment_id,
                            detector_version=self.version,
                        )
                    )
                    occurrence += 1
            index += 1
        return tuple(events)

    @staticmethod
    def _is_entry(previous: float, current: float, rule: EventRule) -> bool:
        threshold = rule.threshold
        if rule.operator in {"crosses_above", "above"}:
            return current > threshold and previous <= threshold
        if rule.operator in {"crosses_below", "below"}:
            return current < threshold and previous >= threshold
        raise ValueError(f"unsupported event operator: {rule.operator}")


def time_for_frame(metrics: MetricTable, frame: int) -> float:
    """Return the exact metric-table time for a frame."""

    try:
        index = metrics.frames.index(frame)
    except ValueError as exc:
        raise KeyError(f"frame not present in metric table: {frame}") from exc
    return metrics.times[index]


def frame_for_time(metrics: MetricTable, time: float) -> int:
    """Return the frame for an exact time, rejecting interpolation."""

    for frame, candidate in zip(metrics.frames, metrics.times):
        if candidate == time:
            return frame
    raise ValueError(f"time is not an exact metric-table sample: {time}")
