"""Small UI status strip for background task state."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TaskStatusStrip(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("status_strip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.label = QLabel("无后台任务")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.cancel_button)

    def set_task(self, name: str, running: bool = True) -> None:
        self.label.setText(f"后台任务：{name}" if running else f"任务完成：{name}")
        self.cancel_button.setEnabled(running)
