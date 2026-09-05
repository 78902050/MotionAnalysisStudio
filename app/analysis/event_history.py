"""Append-only event detection and manual-adjustment history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.io.jsonl import JsonlStore

from .events import Event


@dataclass(frozen=True)
class EventHistoryRecord:
    action: str
    event: Event
    created_at: str


class EventHistory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._store = JsonlStore(self.path)

    def append(self, event: Event) -> None:
        self._append("detected", event)

    def append_manual(self, event: Event) -> None:
        if event.source != "manual":
            event = Event(
                event.event_id,
                event.rule_id,
                event.role,
                event.frame,
                event.time,
                event.value,
                event.segment_id,
                "manual",
                event.note,
                event.detector_version,
            )
        self._append("manual", event)

    def _append(self, action: str, event: Event) -> None:
        self._store.append(
            {
                "action": action,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "event": event.to_dict(),
            }
        )

    def records(self, event_id: str | None = None) -> list[EventHistoryRecord]:
        values, errors = self._store.read()
        if errors:
            raise ValueError("event history is corrupt: " + "; ".join(errors))
        result: list[EventHistoryRecord] = []
        for value in values:
            event_value = value.get("event")
            if not isinstance(event_value, dict):
                raise ValueError("event history record has no event object")
            event = Event.from_dict(event_value)
            if event_id is not None and event.event_id != event_id:
                continue
            result.append(
                EventHistoryRecord(
                    str(value.get("action", "unknown")),
                    event,
                    str(value.get("created_at", "")),
                )
            )
        return result

    def effective_events(self, detected: tuple[Event, ...] | list[Event]) -> tuple[Event, ...]:
        latest: dict[str, Event] = {}
        for record in self.records():
            if record.action == "manual":
                latest[record.event.event_id] = record.event
        effective = [latest.pop(event.event_id, event) for event in detected]
        effective.extend(
            event
            for event in latest.values()
            if event.source == "manual"
        )
        return tuple(sorted(effective, key=lambda event: (event.frame, event.time, event.event_id)))
