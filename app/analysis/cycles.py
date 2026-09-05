"""Cycle construction constrained to a single continuous data segment."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .events import Event


@dataclass(frozen=True)
class CycleDefinition:
    cycle_id: str
    start_rule_id: str
    end_rule_id: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.cycle_id, "cycle_id"),
            (self.start_rule_id, "start_rule_id"),
            (self.end_rule_id, "end_rule_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"cycle definition {field} must not be empty")


@dataclass(frozen=True)
class Cycle:
    cycle_id: str
    rule_id: str
    start_event_id: str
    end_event_id: str
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    duration: float


class CycleBuilder:
    def build(
        self,
        events: tuple[Event, ...] | list[Event],
        definition: CycleDefinition | None = None,
    ) -> tuple[Cycle, ...]:
        pending: dict[tuple[str, str], deque[Event]] = defaultdict(deque)
        cycles: list[Cycle] = []
        ordered = sorted(events, key=lambda event: (event.frame, event.time, event.event_id))
        for event in ordered:
            cycle_rule_id = definition.cycle_id if definition is not None else event.rule_id
            key = (cycle_rule_id, event.segment_id)
            is_start = event.role == "start" and (
                definition is None or event.rule_id == definition.start_rule_id
            )
            is_end = event.role == "end" and (
                definition is None or event.rule_id == definition.end_rule_id
            )
            if is_start:
                pending[key].append(event)
                continue
            if not is_end or not pending[key]:
                continue
            start = pending[key][0]
            if event.frame <= start.frame or event.time <= start.time:
                continue
            pending[key].popleft()
            cycles.append(
                Cycle(
                    f"cycle-{cycle_rule_id}-{start.frame}-{event.frame}",
                    cycle_rule_id,
                    start.event_id,
                    event.event_id,
                    start.frame,
                    event.frame,
                    start.time,
                    event.time,
                    event.time - start.time,
                )
            )
        return tuple(cycles)
