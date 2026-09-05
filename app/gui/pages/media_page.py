"""Background media inventory and camera-to-video mapping page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QTableView, QVBoxLayout, QWidget

from app.application.controller import ApplicationController
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskRequest
from app.tasks.handle import TaskHandle

from ..layout import make_scrollable_panel


@dataclass(frozen=True)
class MediaRecord:
    camera: str
    video_path: str
    fps: float | None
    resolution: str
    duration_seconds: float | None
    issue: str = ""


class MediaTableModel(QAbstractTableModel):
    HEADERS = ("相机", "视频文件", "帧率", "分辨率", "时长", "映射状态")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.records: tuple[MediaRecord, ...] = ()

    def set_records(self, records: tuple[MediaRecord, ...]) -> None:
        self.beginResetModel()
        self.records = tuple(records)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole}:
            return None
        record = self.records[index.row()]
        values = (
            record.camera,
            record.video_path,
            "—" if record.fps is None else f"{record.fps:.3f} fps",
            record.resolution,
            "—" if record.duration_seconds is None else f"{record.duration_seconds:.3f} s",
            record.issue or "可用",
        )
        return values[index.column()]


class MediaPage(QWidget):
    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
        *,
        controller: ApplicationController | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.controller = controller
        self.model = MediaTableModel(self)
        self.scan_count = 0
        self._scanned_project_id = ""
        self._handle: TaskHandle | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)
        self._build_ui()
        if project is not None:
            self.set_project(project)

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("视频素材")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("核对相机与原始视频映射、帧率、分辨率和时长。这里只读取元数据，不修改或转码视频。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)
        self.refresh_button = QPushButton("后台刷新媒体信息")
        self.refresh_button.setObjectName("media_refresh_button")
        self.refresh_button.clicked.connect(lambda: self.scan(force=True))
        layout.addWidget(self.refresh_button)
        self.table = QTableView()
        self.table.setObjectName("media_table")
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.status = QLabel("请先打开项目")
        self.status.setObjectName("media_status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        scroll = make_scrollable_panel(body)
        scroll.setObjectName("media_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_project(self, project: ProjectManager | None) -> None:
        project_id = str(project.manifest.get("project_id", "")) if project is not None else ""
        if project is self.project and project_id == self._scanned_project_id:
            return
        if self._handle is not None:
            self._handle.cancel()
        self._timer.stop()
        self._handle = None
        self.project = project
        self.model.set_records(())
        self._scanned_project_id = ""
        if project is None:
            self.status.setText("请先打开项目")
            return
        self.scan()

    def scan(self, *, force: bool = False) -> None:
        if self.project is None:
            self.status.setText("请先打开项目")
            return
        project_id = str(self.project.manifest.get("project_id", ""))
        if not force and self._scanned_project_id == project_id:
            return
        if self._handle is not None:
            self.status.setText("媒体扫描正在进行")
            return
        self.scan_count += 1
        self._scanned_project_id = project_id
        project = self.project
        if self.controller is not None and self.controller.current_project is project:
            request = TaskRequest(project_id, self.controller.generation, "media-scan", {})
            self._handle = self.controller.start_task(request, lambda token: self._scan_project(project, token))
            self._timer.start()
            self.refresh_button.setEnabled(False)
            self.status.setText("正在后台读取视频元数据…")
            return
        self._finish(self._scan_project(project, CancellationToken()))

    @staticmethod
    def _scan_project(project: ProjectManager, token: CancellationToken) -> tuple[MediaRecord, ...]:
        records: list[MediaRecord] = []
        cameras = project.manifest.get("cameras", [])
        if not isinstance(cameras, list):
            return (MediaRecord("—", "—", None, "—", None, "项目相机清单无效"),)
        for value in cameras:
            token.raise_if_cancelled()
            if not isinstance(value, dict):
                continue
            camera = str(value.get("camera_id", "")).strip() or "未命名相机"
            path_value = value.get("video_path")
            if not isinstance(path_value, str) or not path_value.strip():
                records.append(MediaRecord(camera, "—", None, "—", None, "未配置视频路径"))
                continue
            path = Path(path_value)
            if not path.is_absolute():
                path = project.root / path
            path = path.resolve()
            if not path.is_file():
                records.append(MediaRecord(camera, str(path), None, "—", None, "视频文件不存在"))
                continue
            capture = cv2.VideoCapture(str(path))
            try:
                if not capture.isOpened():
                    records.append(MediaRecord(camera, str(path), None, "—", None, "视频无法打开"))
                    continue
                fps = float(capture.get(cv2.CAP_PROP_FPS))
                frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                valid_fps = fps if fps > 0 else None
                duration = frame_count / fps if fps > 0 and frame_count >= 0 else None
                resolution = f"{width} × {height}" if width > 0 and height > 0 else "—"
                records.append(MediaRecord(camera, str(path), valid_fps, resolution, duration))
            finally:
                capture.release()
        return tuple(records)

    def _poll(self) -> None:
        handle = self._handle
        if handle is None:
            self._timer.stop()
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self._timer.stop()
        self._handle = None
        self.refresh_button.setEnabled(True)
        if self.project is None:
            return
        project_id = str(self.project.manifest.get("project_id", ""))
        generation = self.controller.generation if self.controller is not None else -1
        if result.project_id != project_id or result.generation != generation:
            return
        if result.status != "succeeded" or not isinstance(result.value, tuple):
            self.status.setText(f"媒体扫描失败：{result.error or result.status}")
            return
        self._finish(result.value)

    def _finish(self, records: tuple[MediaRecord, ...]) -> None:
        self.model.set_records(records)
        issues = sum(bool(record.issue) for record in records)
        self.status.setText(f"已读取 {len(records)} 台相机；映射问题 {issues} 个")

    def closeEvent(self, event) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._timer.stop()
        event.accept()
