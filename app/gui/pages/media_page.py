"""Background media inventory and camera-to-video mapping page."""

from __future__ import annotations

from queue import Empty, SimpleQueue
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
from app.media.importer import VideoImportPlan, VideoImportResult, VideoImportService
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
            return "分析视频"
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
        self._operation = ""
        self._import_plan: VideoImportPlan | None = None
        self._import_progress: SimpleQueue[tuple[int, int, str]] = SimpleQueue()
        self._pending_import_summary = ""
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
        heading.setProperty("uiRole", "pageTitle")
        layout.addWidget(heading)
        description = QLabel(
            "导入供 Pose2Sim 分析的视频，并核对相机映射、帧率、分辨率和时长。"
            "视频复制到当前项目，不修改或转码外部文件。"
        )
        description.setWordWrap(True)
        description.setProperty("uiRole", "muted")
        layout.addWidget(description)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新媒体信息")
        self.refresh_button.setObjectName("media_refresh_button")
        self.refresh_button.clicked.connect(lambda: self.scan(force=True))
        actions.addWidget(self.refresh_button)
        self.import_videos_button = QPushButton("导入视频")
        self.import_videos_button.setObjectName("media_import_videos")
        self.import_videos_button.clicked.connect(self._choose_videos)
        actions.addWidget(self.import_videos_button)
        self.cancel_import_button = QPushButton("取消导入")
        self.cancel_import_button.setObjectName("media_cancel_import")
        self.cancel_import_button.clicked.connect(self._cancel_import)
        self.cancel_import_button.setEnabled(False)
        actions.addWidget(self.cancel_import_button)
        self.bind_pose_button = QPushButton("绑定 Pose2Sim 视频")
        self.bind_pose_button.setObjectName("media_bind_pose2sim")
        self.bind_pose_button.clicked.connect(lambda: self._choose_and_bind("pose2sim_overlay"))
        actions.addWidget(self.bind_pose_button)
        self.prefer_original_button = QPushButton("优先分析视频")
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
        self._operation = ""
        self._import_plan = None
        self._pending_import_summary = ""
        self._import_progress = SimpleQueue()
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
            self._operation = "scan"
            self._timer.start()
            self.refresh_button.setEnabled(False)
            self.import_videos_button.setEnabled(False)
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
        if self._operation == "import":
            while True:
                try:
                    completed, total, name = self._import_progress.get_nowait()
                except Empty:
                    break
                self.status.setText(f"正在导入 {completed}/{total}：{name}")
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
        operation = self._operation
        self._operation = ""
        self.refresh_button.setEnabled(True)
        self.import_videos_button.setEnabled(True)
        self.cancel_import_button.setEnabled(False)
        if self.project is None:
            return
        project_id = str(self.project.manifest.get("project_id", ""))
        generation = self.controller.generation if self.controller is not None else -1
        if result.project_id != project_id or result.generation != generation:
            return
        if result.status != "succeeded":
            label = "视频导入" if operation == "import" else "媒体扫描"
            self.status.setText(f"{label}{'已取消' if result.status == 'cancelled' else '失败'}：{result.error or result.status}")
            return
        if operation == "import":
            if not isinstance(result.value, VideoImportResult):
                self.status.setText("视频导入失败：后台任务返回了无效结果")
                return
            plan = self._import_plan
            unmatched = len(plan.unmatched_files) if plan is not None else 0
            parts = [
                f"已导入 {len(result.value.imported)} 个视频",
                f"已映射 {len(result.value.bound_cameras)} 台相机",
            ]
            if result.value.skipped:
                parts.append(f"跳过已有 {len(result.value.skipped)} 个")
            if unmatched:
                parts.append(f"未映射 {unmatched} 个")
            self._pending_import_summary = "；".join(parts)
            self._import_plan = None
            self.sources_changed.emit()
            self._scanned_project_id = ""
            self.scan(force=True)
            return
        if not isinstance(result.value, tuple):
            self.status.setText("媒体扫描失败：后台任务返回了无效结果")
            return
        self._finish(result.value)

    def _finish(self, records: tuple[MediaRecord, ...]) -> None:
        self.model.set_records(records)
        issues = sum(bool(record.issue) for record in records)
        summary = f"已读取 {len(records)} 台相机；映射问题 {issues} 个"
        if self._pending_import_summary:
            summary = f"{self._pending_import_summary}；{summary}"
            self._pending_import_summary = ""
        self.status.setText(summary)

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

    def _choose_videos(self) -> None:
        if self.project is None:
            self.status.setText("请先打开项目")
            return
        if self.controller is None or self.controller.current_project is not self.project:
            self.status.setText("当前项目未连接后台任务控制器")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入 Pose2Sim 分析视频",
            str(self.project.root),
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.m4v);;所有文件 (*)",
        )
        if not paths:
            return
        try:
            plan = VideoImportService.plan(self.project, (Path(path) for path in paths))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "视频导入失败", str(exc))
            return
        if not plan.items:
            self.status.setText(f"没有可导入的视频；未映射 {len(plan.unmatched_files)} 个")
            return
        if plan.requires_confirmation:
            mapping = "\n".join(
                f"{item.camera} ← {item.source.name}"
                for item in plan.items
                if item.match_method == "ordered"
            )
            answer = QMessageBox.question(
                self,
                "确认相机映射",
                "以下文件名无法直接匹配相机，将按自然顺序关联：\n\n"
                + mapping
                + "\n\n确认后开始导入。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText("已取消视频导入，项目未发生变化")
                return
        replace_existing = False
        if any(item.conflict for item in plan.items):
            answer = QMessageBox.question(
                self,
                "项目中已有同名视频",
                "选择“是”替换项目副本，选择“否”跳过已有文件，选择“取消”停止导入。",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                self.status.setText("已取消视频导入，项目未发生变化")
                return
            replace_existing = answer == QMessageBox.StandardButton.Yes
        project = self.project
        request = TaskRequest(
            str(project.manifest["project_id"]),
            self.controller.generation,
            "video-import",
            {"count": len(plan.items)},
        )
        progress_queue = self._import_progress

        def work(token: CancellationToken) -> VideoImportResult:
            return VideoImportService.execute(
                project,
                plan,
                replace_existing=replace_existing,
                token=token,
                progress=lambda completed, total, path: progress_queue.put(
                    (completed, total, path.name)
                ),
            )

        self._import_plan = plan
        self._handle = self.controller.start_task(request, work)
        self._operation = "import"
        self.refresh_button.setEnabled(False)
        self.import_videos_button.setEnabled(False)
        self.cancel_import_button.setEnabled(True)
        self.status.setText(f"正在导入 0/{len(plan.items)}")
        self._timer.start()

    def _cancel_import(self) -> None:
        if self._handle is None or self._operation != "import":
            return
        self._handle.cancel()
        self.cancel_import_button.setEnabled(False)
        self.status.setText("正在取消视频导入…")

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
