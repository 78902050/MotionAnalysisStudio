"""Small UI status strip for cancellable background task state."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app.tasks.handle import TaskHandle


class TaskStatusStrip(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("status_strip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel("无后台任务")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_active)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.cancel_button)
        self._active_handle: TaskHandle | None = None
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(100)
        self._status_timer.timeout.connect(self.refresh_status)

    def set_task(self, name: str, running: bool = True) -> None:
        self._active_handle = None
        self._status_timer.stop()
        self.label.setText(f"后台任务：{name}" if running else f"任务完成：{name}")
        self.cancel_button.setEnabled(running)

    def set_handle(self, handle: TaskHandle) -> None:
        """Display a handle without waiting for it on the GUI thread."""

        self._active_handle = handle
        self.label.setText(f"后台任务：{handle.name}")
        self.cancel_button.setEnabled(True)
        self._status_timer.start()

    def refresh_status(self) -> None:
        handle = self._active_handle
        if handle is None:
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self._status_timer.stop()
        self.cancel_button.setEnabled(False)
        labels = {
            "succeeded": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }
        self.label.setText(f"任务{labels[result.status]}：{handle.name}")
        self._active_handle = None

    def _cancel_active(self) -> None:
        handle = self._active_handle
        if handle is None:
            return
        handle.cancel()
        self.label.setText(f"正在取消：{handle.name}")
        self.cancel_button.setEnabled(False)
