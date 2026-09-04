"""Cycle construction constrained to a single continuous data segment."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .events import Event


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
    def build(self, events: tuple[Event, ...] | list[Event]) -> tuple[Cycle, ...]:
        pending: dict[tuple[str, str], deque[Event]] = defaultdict(deque)
        cycles: list[Cycle] = []
        ordered = sorted(events, key=lambda event: (event.frame, event.time, event.event_id))
        for event in ordered:
            key = (event.rule_id, event.segment_id)
            if event.role == "start":
                pending[key].append(event)
                continue
            if event.role != "end" or not pending[key]:
                continue
            start = pending[key][0]
            if event.frame <= start.frame or event.time <= start.time:
                continue
            pending[key].popleft()
            cycles.append(
                Cycle(
                    f"cycle-{event.rule_id}-{start.frame}-{event.frame}",
                    event.rule_id,
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
