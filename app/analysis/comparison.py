"""Traceable comparison of selected people and trials."""

from __future__ import annotations

import math
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping

from .events import Event
from .model import MetricTable


Alignment = Literal["frame", "time", "event"]


def _ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty IDs")
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class ComparisonRequest:
    project_ids: tuple[str, ...]
    person_ids: tuple[str, ...]
    trial_ids: tuple[str, ...]
    alignment: Alignment

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_ids", _ids(self.project_ids, "project_ids"))
        object.__setattr__(self, "person_ids", _ids(self.person_ids, "person_ids"))
        object.__setattr__(self, "trial_ids", _ids(self.trial_ids, "trial_ids"))
        if self.alignment not in {"frame", "time", "event"}:
            raise ValueError(f"unsupported comparison alignment: {self.alignment}")

    def to_dict(self) -> dict[str, object]:
        return {
            "project_ids": list(self.project_ids),
            "person_ids": list(self.person_ids),
            "trial_ids": list(self.trial_ids),
            "alignment": self.alignment,
        }


def _input_version(table: MetricTable) -> str:
    metadata_version = table.metadata.get("input_version")
    if isinstance(metadata_version, str) and metadata_version.strip():
        return metadata_version
    versions = {
        str(value.get("input_version"))
        for value in table.provenance.values()
        if isinstance(value.get("input_version"), str) and str(value.get("input_version")).strip()
    }
    if len(versions) == 1:
        return next(iter(versions))
    source_version = table.metadata.get("source_version")
    if isinstance(source_version, str) and source_version.strip():
        return source_version
    return "unknown"


@dataclass(frozen=True)
class ComparisonMember:
    project_id: str
    person_id: str
    trial_id: str
    metrics: MetricTable
    events: tuple[Event, ...] = ()
    input_version: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.project_id, "project_id"),
            (self.person_id, "person_id"),
            (self.trial_id, "trial_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.metrics, MetricTable):
            raise TypeError("comparison member metrics must be a MetricTable")
        events = tuple(self.events)
        if any(not isinstance(event, Event) for event in events):
            raise TypeError("comparison member events must contain Event objects")
        object.__setattr__(self, "events", events)
        version = self.input_version or _input_version(self.metrics)
        object.__setattr__(self, "input_version", version)

    @property
    def member_id(self) -> str:
        return f"{self.project_id}/{self.person_id}/{self.trial_id}"


@dataclass(frozen=True)
class ComparisonRow:
    alignment_key: str
    member_id: str
    project_id: str
    person_id: str
    trial_id: str
    metric: str
    frame: int | None
    time: float | None
    value: float | None
    missing_reason: str | None = None
    event_id: str | None = None
    unit: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "alignment_key": self.alignment_key,
            "member_id": self.member_id,
            "project_id": self.project_id,
            "person_id": self.person_id,
            "trial_id": self.trial_id,
            "metric": self.metric,
            "frame": self.frame,
            "time": self.time,
            "value": self.value,
            "missing_reason": self.missing_reason,
            "event_id": self.event_id,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class ComparisonReport:
    report_id: str
    report_version: str
    request: ComparisonRequest
    member_ids: tuple[str, ...]
    rows: tuple[ComparisonRow, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
    summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_ids", tuple(self.member_ids))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "summary", dict(self.summary))

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "report_version": self.report_version,
            "request": self.request.to_dict(),
            "member_ids": list(self.member_ids),
            "metadata": dict(self.metadata),
            "summary": dict(self.summary),
            "rows": [row.to_dict() for row in self.rows],
        }


class ComparisonService:
    def __init__(self, members: Iterable[ComparisonMember] = ()) -> None:
        self._members: dict[str, ComparisonMember] = {}
        for member in members:
            self.register(member)

    def register(self, member: ComparisonMember) -> None:
        if member.member_id in self._members:
            raise ValueError(f"duplicate comparison member: {member.member_id}")
        self._members[member.member_id] = member

    def build(self, request: ComparisonRequest) -> ComparisonReport:
        selected = sorted(
            (
                member
                for member in self._members.values()
                if member.project_id in request.project_ids
                and member.person_id in request.person_ids
                and member.trial_id in request.trial_ids
            ),
            key=lambda member: member.member_id,
        )
        if not selected:
            raise ValueError("comparison request did not select any registered member")
        columns = tuple(sorted({column for member in selected for column in member.metrics.columns}))
        if not columns:
            raise ValueError("selected comparison members have no metric columns")
        self._validate_compatibility(selected, columns, request.alignment)
        if request.alignment == "frame":
            rows = self._rows_by_frame(selected, columns)
            alignment_source = "exact metric frames; no interpolation"
        elif request.alignment == "time":
            rows = self._rows_by_time(selected, columns)
            alignment_source = "exact metric times; no interpolation"
        else:
            rows = self._rows_by_event(selected, columns)
            alignment_source = "event rule and occurrence; exact event frame"
        member_ids = tuple(member.member_id for member in selected)
        metadata = {
            "alignment": request.alignment,
            "alignment_source": alignment_source,
            "metric_columns": columns,
            "member_count": len(selected),
            "input_versions": {member.member_id: member.input_version for member in selected},
            "metric_contracts": {
                column: next(
                    member.metrics.contract(column).to_dict()
                    for member in selected
                    if column in member.metrics.columns
                )
                for column in columns
            },
            "missing_value_policy": "missing values remain null with missing_reason; never zero-filled",
        }
        summary = self._summary(rows, member_ids, columns)
        report_id = self._report_id(request, selected, columns)
        from app.reporting.report_builder import ReportBuilder

        return ReportBuilder().build(report_id, request, member_ids, rows, metadata, summary)

    def export(self, report: ComparisonReport, path, format: Literal["json", "csv", "html"]) -> None:
        from app.reporting.export import ReportExporter

        ReportExporter().export(report, path, format)

    @staticmethod
    def _report_id(
        request: ComparisonRequest,
        members: list[ComparisonMember],
        columns: tuple[str, ...],
    ) -> str:
        member_ids = tuple(member.member_id for member in members)
        raw = "-".join((request.alignment, *member_ids))
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")
        identity = {
            "request": request.to_dict(),
            "members": [
                {
                    "member_id": member.member_id,
                    "input_version": member.input_version,
                    "contracts": {
                        column: member.metrics.contract(column).to_dict()
                        for column in columns
                        if column in member.metrics.columns
                    },
                }
                for member in members
            ],
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        return f"comparison-v1-{slug or request.alignment}-{digest}"

    @staticmethod
    def _validate_compatibility(
        members: list[ComparisonMember],
        columns: tuple[str, ...],
        alignment: Alignment,
    ) -> None:
        for column in columns:
            contracts = [
                (member.member_id, member.metrics.contract(column))
                for member in members
                if column in member.metrics.columns
            ]
            if len(contracts) < 2:
                continue
            baseline_id, baseline = contracts[0]
            for member_id, contract in contracts[1:]:
                if not baseline.compatible_with(contract):
                    raise ValueError(
                        f"incompatible metric contract for {column}: {baseline_id} vs {member_id}"
                    )
        if alignment == "event":
            versions = {
                event.detector_version
                for member in members
                for event in member.events
            }
            if len(versions) > 1:
                raise ValueError("incompatible event detector versions for event alignment")

    @classmethod
    def _rows_by_frame(cls, members: list[ComparisonMember], columns: tuple[str, ...]) -> tuple[ComparisonRow, ...]:
        frames = sorted({frame for member in members for frame in member.metrics.frames})
        return tuple(
            row
            for frame in frames
            for member in members
            for column in columns
            for row in (cls._row_for_frame(member, column, frame),)
        )

    @classmethod
    def _rows_by_time(cls, members: list[ComparisonMember], columns: tuple[str, ...]) -> tuple[ComparisonRow, ...]:
        times = sorted({time for member in members for time in member.metrics.times if math.isfinite(time)})
        return tuple(
            row
            for time in times
            for member in members
            for column in columns
            for row in (cls._row_for_time(member, column, time),)
        )

    @classmethod
    def _rows_by_event(cls, members: list[ComparisonMember], columns: tuple[str, ...]) -> tuple[ComparisonRow, ...]:
        grouped: dict[str, dict[str, tuple[Event, ...]]] = defaultdict(dict)
        for member in members:
            by_rule: dict[str, list[Event]] = defaultdict(list)
            for event in member.events:
                by_rule[event.rule_id].append(event)
            for rule_id, events in by_rule.items():
                grouped[rule_id][member.member_id] = tuple(
                    sorted(events, key=lambda event: (event.time, event.frame, event.event_id))
                )
        keys = sorted((rule_id, index) for rule_id, by_member in grouped.items() for index in range(max((len(events) for events in by_member.values()), default=0)))
        if not keys:
            raise ValueError("event alignment requires at least one event")
        rows: list[ComparisonRow] = []
        for rule_id, index in keys:
            alignment_key = f"{rule_id}:{index}"
            for member in members:
                event_list = grouped[rule_id].get(member.member_id, ())
                event = event_list[index] if index < len(event_list) else None
                for column in columns:
                    rows.append(cls._row_for_event(member, column, alignment_key, event))
        return tuple(rows)

    @staticmethod
    def _row_for_frame(member: ComparisonMember, column: str, frame: int) -> ComparisonRow:
        index_by_frame = {value: index for index, value in enumerate(member.metrics.frames)}
        index = index_by_frame.get(frame)
        if index is None:
            return ComparisonRow(frame.__str__(), member.member_id, member.project_id, member.person_id, member.trial_id, column, frame, None, None, "sample_missing", unit=member.metrics.units.get(column))
        return ComparisonService._row_from_index(member, column, str(frame), index)

    @staticmethod
    def _row_for_time(member: ComparisonMember, column: str, time: float) -> ComparisonRow:
        index = next((index for index, candidate in enumerate(member.metrics.times) if candidate == time), None)
        if index is None:
            return ComparisonRow(f"{time:g}", member.member_id, member.project_id, member.person_id, member.trial_id, column, None, time, None, "sample_missing", unit=member.metrics.units.get(column))
        return ComparisonService._row_from_index(member, column, f"{time:g}", index)

    @staticmethod
    def _row_from_index(member: ComparisonMember, column: str, alignment_key: str, index: int) -> ComparisonRow:
        frame = member.metrics.frames[index]
        time = member.metrics.times[index]
        if column not in member.metrics.columns:
            return ComparisonRow(alignment_key, member.member_id, member.project_id, member.person_id, member.trial_id, column, frame, time, None, "metric_missing")
        value = member.metrics.columns[column][index]
        if not math.isfinite(value):
            return ComparisonRow(alignment_key, member.member_id, member.project_id, member.person_id, member.trial_id, column, frame, time, None, "missing_value", unit=member.metrics.units[column])
        return ComparisonRow(alignment_key, member.member_id, member.project_id, member.person_id, member.trial_id, column, frame, time, value, unit=member.metrics.units[column])

    @staticmethod
    def _row_for_event(member: ComparisonMember, column: str, alignment_key: str, event: Event | None) -> ComparisonRow:
        if event is None:
            return ComparisonRow(alignment_key, member.member_id, member.project_id, member.person_id, member.trial_id, column, None, None, None, "event_missing", unit=member.metrics.units.get(column))
        index = next((index for index, frame in enumerate(member.metrics.frames) if frame == event.frame), None)
        if index is None:
            return ComparisonRow(alignment_key, member.member_id, member.project_id, member.person_id, member.trial_id, column, event.frame, event.time, None, "event_frame_missing", event.event_id, member.metrics.units.get(column))
        row = ComparisonService._row_from_index(member, column, alignment_key, index)
        return ComparisonRow(row.alignment_key, row.member_id, row.project_id, row.person_id, row.trial_id, row.metric, row.frame, row.time, row.value, row.missing_reason, event.event_id, row.unit)

    @staticmethod
    def _summary(rows: tuple[ComparisonRow, ...], member_ids: tuple[str, ...], columns: tuple[str, ...]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for member_id in member_ids:
            member_summary: dict[str, object] = {}
            for column in columns:
                values = [row.value for row in rows if row.member_id == member_id and row.metric == column and row.value is not None]
                member_summary[column] = {
                    "finite_count": len(values),
                    "missing_count": sum(1 for row in rows if row.member_id == member_id and row.metric == column and row.value is None),
                    "mean": sum(values) / len(values) if values else None,
                }
            summary[member_id] = member_summary
        return summary
