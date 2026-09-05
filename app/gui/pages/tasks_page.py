"""Read-only background-task list with explicit cancellation."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.tasks.supervisor import TaskSupervisor


class TasksPage(QWidget):
    def __init__(self, supervisor: TaskSupervisor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.supervisor = supervisor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("任务与日志")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("查看后台阶段、项目代次和失败原因；取消会终止该任务及其子进程。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)
        self.task_list = QListWidget()
        self.task_list.setObjectName("task_list")
        self.task_list.currentItemChanged.connect(self._show_selected_details)
        layout.addWidget(self.task_list, 1)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        self.cancel_button = QPushButton("取消所选任务")
        self.cancel_button.setObjectName("task_cancel_button")
        self.cancel_button.clicked.connect(self.cancel_selected)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status = QLabel("无后台任务")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        selected = self.task_list.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.task_list.clear()
        snapshots = self.supervisor.snapshots()
        for snapshot in snapshots:
            item = QListWidgetItem(
                f"[{snapshot.status}] {snapshot.name}  ·  代次 {snapshot.generation}"
            )
            item.setData(Qt.ItemDataRole.UserRole, snapshot.task_id)
            if snapshot.error:
                item.setToolTip(snapshot.error)
            self.task_list.addItem(item)
            if snapshot.task_id == selected_id:
                self.task_list.setCurrentItem(item)
        self.status.setText(f"共 {len(snapshots)} 个任务" if snapshots else "无后台任务")

    def _show_selected_details(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        if current is None:
            return
        task_id = str(current.data(Qt.ItemDataRole.UserRole))
        try:
            snapshot = self.supervisor.snapshot(task_id)
        except KeyError:
            return
        self.status.setText(
            f"任务 {snapshot.task_id} · 项目 {snapshot.project_id} · 代次 {snapshot.generation}"
            + (f"\n{snapshot.error}" if snapshot.error else "")
        )

    def cancel_selected(self) -> None:
        item = self.task_list.currentItem()
        if item is None:
            self.status.setText("请选择要取消的任务")
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.supervisor.cancel(str(task_id))
        except KeyError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText("已请求取消")
        self.refresh()
