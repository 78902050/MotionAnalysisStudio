"""Correction session state, dispositions, and in-memory undo/redo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.domain.addresses import CorrectionTarget
from app.io.atomic import AtomicJsonStore
from app.pose_editor.model import PoseDocument

from .model import CorrectionOperation, IssueDisposition


class CorrectionSession:
    def __init__(
        self,
        document: PoseDocument,
        project_root: Path | None = None,
        session_id: str | None = None,
    ) -> None:
        self.document = document
        self.project_root = Path(project_root) if project_root is not None else document.project_root
        self.session_id = session_id or f"session-{uuid4().hex}"
        self._targets: list[CorrectionTarget] = []
        self._issue_ids: list[str] = []
        self._dispositions: dict[str, IssueDisposition] = {}
        self._current_index = -1
        self._undo_stack: list[CorrectionOperation] = []
        self._redo_stack: list[CorrectionOperation] = []
        self._load_state()

    @property
    def issue_ids(self) -> tuple[str, ...]:
        return tuple(self._issue_ids)

    def open(
        self,
        issues: Iterable[CorrectionTarget],
        issue_ids: Iterable[str] | None = None,
    ) -> None:
        self._targets = list(issues)
        if issue_ids is None:
            self._issue_ids = [f"issue-{index + 1}" for index in range(len(self._targets))]
        else:
            self._issue_ids = list(issue_ids)
            if len(self._issue_ids) != len(self._targets):
                raise ValueError("issue ID count must match correction target count")
            if any(not issue_id.strip() for issue_id in self._issue_ids):
                raise ValueError("issue IDs must not be empty")
            if len(set(self._issue_ids)) != len(self._issue_ids):
                raise ValueError("issue IDs must be unique")
        self._current_index = 0 if self._targets else -1
        for issue_id in self._issue_ids:
            self._dispositions.setdefault(issue_id, IssueDisposition(issue_id, "pending"))
        self._persist_state()

    def current(self) -> CorrectionTarget | None:
        if self._current_index < 0 or self._current_index >= len(self._targets):
            return None
        return self._targets[self._current_index]

    def next_issue(self) -> CorrectionTarget | None:
        if not self._targets:
            return None
        self._current_index = min(self._current_index + 1, len(self._targets) - 1)
        return self.current()

    def previous_issue(self) -> CorrectionTarget | None:
        if not self._targets:
            return None
        self._current_index = max(self._current_index - 1, 0)
        return self.current()

    def set_disposition(self, issue_id: str, disposition: IssueDisposition | str, note: str = "") -> None:
        if issue_id not in self._issue_ids:
            raise KeyError(f"unknown issue: {issue_id}")
        value = disposition if isinstance(disposition, IssueDisposition) else IssueDisposition(issue_id, disposition, note)
        if value.issue_id != issue_id:
            value = IssueDisposition(issue_id, value.status, value.note)
        self._dispositions[issue_id] = value
        self._persist_state()

    def disposition(self, issue_id: str) -> IssueDisposition:
        return self._dispositions.get(issue_id, IssueDisposition(issue_id, "pending"))

    def apply_point(self, target: CorrectionTarget, x: float, y: float, confidence: float = 1.0) -> None:
        operation = self.document.set_point_value(
            target,
            (x, y, confidence),
            session_id=self.session_id,
            source="manual",
        )
        assert operation is not None
        self._undo_stack.append(operation)
        self._redo_stack.clear()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        operation = self._undo_stack.pop()
        self.document.set_point_value(
            operation.target,
            operation.before,
            session_id=self.session_id,
            source=operation.source,
            record=False,
        )
        self._redo_stack.append(operation)

    def redo(self) -> None:
        if not self._redo_stack:
            return
        operation = self._redo_stack.pop()
        self.document.set_point_value(
            operation.target,
            operation.after,
            session_id=self.session_id,
            source=operation.source,
            record=False,
        )
        self._undo_stack.append(operation)

    def reset_frame(self, frame: int) -> None:
        removed = [operation for operation in self._undo_stack if operation.target.address.frame == frame]
        for operation in reversed(removed):
            self.document.set_point_value(
                operation.target,
                operation.before,
                session_id=self.session_id,
                source=operation.source,
                record=False,
            )
        self._undo_stack = [operation for operation in self._undo_stack if operation.target.address.frame != frame]
        self._redo_stack.clear()
        self.document.remove_pending({operation.operation_id for operation in removed})

    def has_unsaved_changes(self) -> bool:
        return self.document.has_net_changes()

    def save(self, note: str = "") -> tuple[int, list[str]]:
        result = self.document.save(note=note, session_id=self.session_id)
        self._undo_stack.clear()
        self._redo_stack.clear()
        return result

    def discard_unsaved(self) -> None:
        self.document.discard_unsaved()
        self._undo_stack.clear()
        self._redo_stack.clear()

    def navigate_to(self, target: CorrectionTarget, decision: str = "cancel") -> bool:
        if self.has_unsaved_changes():
            if decision == "save":
                self.save()
            elif decision == "discard":
                self.discard_unsaved()
            else:
                return False
        try:
            self._current_index = self._targets.index(target)
        except ValueError:
            return False
        return True

    @property
    def _state_path(self) -> Path:
        return self.project_root / "corrections" / "sessions" / f"{self.session_id}.json"

    def _load_state(self) -> None:
        if not self._state_path.is_file():
            return
        value = json.loads(self._state_path.read_text(encoding="utf-8"))
        dispositions = value.get("dispositions", []) if isinstance(value, dict) else []
        if isinstance(dispositions, list):
            for item in dispositions:
                if isinstance(item, dict):
                    disposition = IssueDisposition.from_dict(item)
                    self._dispositions[disposition.issue_id] = disposition

    def _persist_state(self) -> None:
        AtomicJsonStore.replace(
            self._state_path,
            {
                "session_id": self.session_id,
                "issue_ids": self._issue_ids,
                "dispositions": [item.to_dict() for item in self._dispositions.values()],
            },
        )
