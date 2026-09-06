"""Background media inventory and camera-to-video mapping page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.application.controller import ApplicationController
from app.media.bindings import VideoBindingService
from app.media.video_sources import VideoSourceResolver
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskRequest
from app.tasks.handle import TaskHandle

from ..layout import make_scrollable_panel


def _declared_source(
    project: ProjectManager, record: dict[str, object]
) -> tuple[Path, str] | None:
    preferred = record.get("preferred_video_kind")
    fields = (
        (("pose_video_path", "pose2sim_overlay"), ("video_path", "original"))
        if preferred == "pose2sim_overlay"
        else (("video_path", "original"), ("pose_video_path", "pose2sim_overlay"))
    )
    for field, kind in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        if not path.is_absolute():
            path = project.root / path
        return path.resolve(), kind
    return None


@dataclass(frozen=True)
class MediaRecord:
    camera: str
    video_path: str
    fps: float | None
    resolution: str
    duration_seconds: float | None
    issue: str = ""
    source_kind: str = ""

    @property
    def source_label(self) -> str:
        if self.source_kind == "original":
            return "原视频"
        if self.source_kind == "pose2sim_overlay":
            return "Pose2Sim 二维标记视频"
        return "未绑定"


class MediaTableModel(QAbstractTableModel):
    HEADERS = ("相机", "当前来源", "视频文件", "帧率", "分辨率", "时长", "映射状态")

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
            record.source_label,
            record.video_path,
            "—" if record.fps is None else f"{record.fps:.3f} fps",
            record.resolution,
            "—" if record.duration_seconds is None else f"{record.duration_seconds:.3f} s",
            record.issue or "可用",
        )
        return values[index.column()]


class MediaPage(QWidget):
    sources_changed = Signal()

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
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新媒体信息")
        self.refresh_button.setObjectName("media_refresh_button")
        self.refresh_button.clicked.connect(lambda: self.scan(force=True))
        actions.addWidget(self.refresh_button)
        self.bind_original_button = QPushButton("绑定原视频")
        self.bind_original_button.setObjectName("media_bind_original")
        self.bind_original_button.clicked.connect(lambda: self._choose_and_bind("original"))
        actions.addWidget(self.bind_original_button)
        self.bind_pose_button = QPushButton("绑定 Pose2Sim 视频")
        self.bind_pose_button.setObjectName("media_bind_pose2sim")
        self.bind_pose_button.clicked.connect(lambda: self._choose_and_bind("pose2sim_overlay"))
        actions.addWidget(self.bind_pose_button)
        self.prefer_original_button = QPushButton("优先原视频")
        self.prefer_original_button.clicked.connect(lambda: self._set_preferred("original"))
        actions.addWidget(self.prefer_original_button)
        self.prefer_pose_button = QPushButton("优先标记视频")
        self.prefer_pose_button.clicked.connect(lambda: self._set_preferred("pose2sim_overlay"))
        actions.addWidget(self.prefer_pose_button)
        self.clear_button = QPushButton("清除当前来源")
        self.clear_button.setObjectName("media_clear_binding")
        self.clear_button.clicked.connect(self._clear_current)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
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
        sources = VideoSourceResolver.resolve(project)
        cameras = project.manifest.get("cameras", [])
        if not isinstance(cameras, list):
            return (MediaRecord("—", "—", None, "—", None, "项目相机清单无效"),)
        for value in cameras:
            token.raise_if_cancelled()
            if not isinstance(value, dict):
                continue
            camera = str(value.get("camera_id", "")).strip() or "未命名相机"
            source = sources.get(camera)
            if source is None:
                declared = _declared_source(project, value)
                if declared is None:
                    records.append(MediaRecord(camera, "—", None, "—", None, "未配置视频路径"))
                else:
                    path, kind = declared
                    records.append(
                        MediaRecord(camera, str(path), None, "—", None, "视频文件不存在", kind)
                    )
                continue
            path = source.path
            capture = cv2.VideoCapture(str(path))
            try:
                if not capture.isOpened():
                    records.append(MediaRecord(camera, str(path), None, "—", None, "视频无法打开", source.kind))
                    continue
                fps = float(capture.get(cv2.CAP_PROP_FPS))
                frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                valid_fps = fps if fps > 0 else None
                duration = frame_count / fps if fps > 0 and frame_count >= 0 else None
                resolution = f"{width} × {height}" if width > 0 and height > 0 else "—"
                records.append(MediaRecord(camera, str(path), valid_fps, resolution, duration, "", source.kind))
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

    def _selected_camera(self) -> str | None:
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.model.records):
            self.status.setText("请先在表格中选择一台相机")
            return None
        return self.model.records[index.row()].camera

    def _choose_and_bind(self, kind: str) -> None:
        camera = self._selected_camera()
        if camera is None or self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择原视频" if kind == "original" else "选择 Pose2Sim 二维标记视频",
            str(self.project.root),
            "视频文件 (*.mp4 *.avi *.mov *.mkv);;所有文件 (*)",
        )
        if not path:
            return
        try:
            VideoBindingService.bind(self.project, camera, Path(path), kind)  # type: ignore[arg-type]
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "视频绑定失败", str(exc))
            return
        self.sources_changed.emit()
        self._scanned_project_id = ""
        self.scan(force=True)

    def _set_preferred(self, kind: str) -> None:
        camera = self._selected_camera()
        if camera is None or self.project is None:
            return
        try:
            VideoBindingService.set_preferred(self.project, camera, kind)  # type: ignore[arg-type]
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            return
        self.sources_changed.emit()
        self._scanned_project_id = ""
        self.scan(force=True)

    def _clear_current(self) -> None:
        camera = self._selected_camera()
        if camera is None or self.project is None:
            return
        source = VideoSourceResolver.resolve(self.project).get(camera)
        if source is None:
            self.status.setText("所选相机没有可清除的视频来源")
            return
        VideoBindingService.clear(self.project, camera, source.kind)
        self.sources_changed.emit()
        self._scanned_project_id = ""
        self.scan(force=True)

    def closeEvent(self, event) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._timer.stop()
        event.accept()
