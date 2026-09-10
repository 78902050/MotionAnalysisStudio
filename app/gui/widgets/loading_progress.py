"""Consistent visual progress feedback for user-visible loading work."""

from __future__ import annotations

from PySide6.QtWidgets import QProgressBar, QWidget


class LoadingProgressBar(QProgressBar):
    """A progress bar that supports both measured and indeterminate operations."""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setTextVisible(True)
        self.setVisible(False)

    def begin(self, message: str, *, total: int | None = None) -> None:
        if total is None or total <= 0:
            self.setRange(0, 0)
        else:
            self.setRange(0, total)
            self.setValue(0)
        self.setFormat(message)
        self.setVisible(True)

    def set_progress(self, completed: int, total: int, message: str) -> None:
        if total <= 0:
            self.begin(message)
            return
        self.setRange(0, total)
        self.setValue(min(max(completed, 0), total))
        self.setFormat(message)
        self.setVisible(True)

    def finish(self) -> None:
        self.setVisible(False)
        self.setRange(0, 1)
        self.setValue(0)
