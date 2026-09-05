"""Resizable Pose2Sim stage runner with Config editor and live log tail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.dirty_state import DirtyState
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.pose2sim.config_document import ConfigDocument, ConfigSyntaxError
from app.project.manager import ProjectManager
from app.tasks.handle import TaskHandle

from ..layout import make_resizable_splitter, make_scrollable_panel


_STAGE_LABELS = {
    "calibration": "相机标定",
    "synchronization": "视频同步",
    "poseEstimation": "二维姿态估计",
    "personAssociation": "多人关联",
    "triangulation": "三角化",
    "filtering": "滤波",
    "markerAugmentation": "标记点增强",
    "kinematics": "运动学",
}


class PipelinePage(QWidget):
    pipeline_finished = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, launcher: Any = None, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.launcher = launcher
        self.settings = settings or QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self.project: ProjectManager | None = None
        self.document: ConfigDocument | None = None
        self._handle: TaskHandle | None = None
        self._log_path: Path | None = None
        self._log_offset = 0
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll_run)
        self.clear_project()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("Pose2Sim 流程")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        header.addWidget(title)
        header.addStretch(1)
        self.run_status = QLabel("未打开项目")
        self.run_status.setObjectName("pipeline_run_status")
        header.addWidget(self.run_status)
        root.addLayout(header)

        self.stage_list = QListWidget()
        self.stage_list.setObjectName("pipeline_stage_list")
        self.stage_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for stage in GENERAL_POSE2SIM_STAGES:
            item = QListWidgetItem(_STAGE_LABELS[stage])
            item.setData(Qt.ItemDataRole.UserRole, stage)
            self.stage_list.addItem(item)
        self.stage_list.setCurrentRow(0)
        self.run_current_button = QPushButton("运行当前阶段")
        self.run_current_button.setObjectName("pipeline_run_current_button")
        self.run_current_button.clicked.connect(self.run_current)
        self.run_selected_button = QPushButton("运行选中阶段")
        self.run_selected_button.setObjectName("pipeline_run_selected_button")
        self.run_selected_button.clicked.connect(self.run_selected)
        self.run_from_button = QPushButton("从当前阶段运行到末尾")
        self.run_from_button.setObjectName("pipeline_run_from_button")
        self.run_from_button.clicked.connect(self.run_from_current)
        self.cancel_button = QPushButton("取消运行")
        self.cancel_button.setObjectName("pipeline_cancel_button")
        self.cancel_button.clicked.connect(self.cancel_run)
        left_body = QWidget()
        left_layout = QVBoxLayout(left_body)
        left_layout.addWidget(QLabel("阶段（可多选）"))
        left_layout.addWidget(self.stage_list)
        left_layout.addWidget(self.run_current_button)
        left_layout.addWidget(self.run_selected_button)
        left_layout.addWidget(self.run_from_button)
        left_layout.addWidget(self.cancel_button)
        left_scroll = make_scrollable_panel(left_body)
        left_scroll.setObjectName("pipeline_controls_scroll")

        config_panel = QFrame()
        config_layout = QVBoxLayout(config_panel)
        config_header = QHBoxLayout()
        config_header.addWidget(QLabel("Config.toml"))
        config_header.addStretch(1)
        self.save_config_button = QPushButton("保存配置")
        self.save_config_button.clicked.connect(self.save)
        self.reload_config_button = QPushButton("重新载入")
        self.reload_config_button.clicked.connect(self.reload)
        config_header.addWidget(self.save_config_button)
        config_header.addWidget(self.reload_config_button)
        config_layout.addLayout(config_header)
        self.config_editor = QPlainTextEdit()
        self.config_editor.setObjectName("pipeline_config_editor")
        self.config_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.config_editor.textChanged.connect(self._validate_editor)
        config_layout.addWidget(self.config_editor, 1)
        self.config_status = QLabel("—")
        self.config_status.setObjectName("pipeline_config_status")
        self.config_status.setWordWrap(True)
        config_layout.addWidget(self.config_status)

        log_panel = QFrame()
        log_layout = QVBoxLayout(log_panel)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("实时日志"))
        log_header.addStretch(1)
        self.open_log_button = QPushButton("打开日志")
        self.open_log_button.clicked.connect(self.open_log)
        log_header.addWidget(self.open_log_button)
        log_layout.addLayout(log_header)
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setObjectName("pipeline_log_viewer")
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log_layout.addWidget(self.log_viewer, 1)

        self.splitter = make_resizable_splitter(left_scroll, config_panel, log_panel)
        self.splitter.setObjectName("pipeline_splitter")
        self.splitter.setSizes([220, 460, 440])
        saved_sizes = self.settings.value("pipeline/splitter_sizes")
        if isinstance(saved_sizes, list) and len(saved_sizes) == 3:
            self.splitter.setSizes([int(size) for size in saved_sizes])
        self.splitter.splitterMoved.connect(lambda *_: self.settings.setValue("pipeline/splitter_sizes", self.splitter.sizes()))
        root.addWidget(self.splitter, 1)

    def clear_project(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
        if hasattr(self, "_timer"):
            self._timer.stop()
        self._handle = None
        self.project = None
        self.document = None
        self.config_editor.blockSignals(True)
        self.config_editor.clear()
        self.config_editor.blockSignals(False)
        self.config_editor.setEnabled(False)
        self.config_status.setText("请先打开项目")
        self.run_status.setText("未打开项目")
        self.log_viewer.clear()
        self._set_action_state(False)

    def set_project(self, project: ProjectManager | None) -> None:
        if project is None:
            self.clear_project()
            return
        if self._handle is not None:
            self._handle.cancel()
        self._timer.stop()
        self._handle = None
        self.project = project
        try:
            self.document = ConfigDocument.open(project.path_for("config"))
            text = self.document.text
        except (OSError, ConfigSyntaxError) as exc:
            self.document = None
            text = ""
            self.config_status.setText(f"配置读取失败：{exc}")
        self.config_editor.blockSignals(True)
        self.config_editor.setPlainText(text)
        self.config_editor.blockSignals(False)
        self.config_editor.setEnabled(self.document is not None)
        self.log_viewer.clear()
        self._log_path = None
        self._log_offset = 0
        self.run_status.setText("就绪")
        self.refresh_stages()
        self._validate_editor()

    def refresh_stages(self) -> None:
        selected = {str(item.data(Qt.ItemDataRole.UserRole)) for item in self.stage_list.selectedItems()}
        stages = self.project.manifest.get("stages", {}) if self.project is not None else {}
        for row, stage in enumerate(GENERAL_POSE2SIM_STAGES):
            item = self.stage_list.item(row)
            record = stages.get(stage, {}) if isinstance(stages, dict) else {}
            status = record.get("status", "not_started") if isinstance(record, dict) else "not_started"
            item.setText(f"{_STAGE_LABELS[stage]}  [{status}]")
            item.setSelected(stage in selected)

    def _validate_editor(self) -> None:
        if self.document is None:
            self._set_action_state(False)
            return
        validation = self.document.validate(self.config_editor.toPlainText())
        self.config_status.setText(validation.message)
        self._set_action_state(validation.valid and self._handle is None)

    def _set_action_state(self, runnable: bool) -> None:
        for button in (self.run_current_button, self.run_selected_button, self.run_from_button):
            button.setEnabled(runnable and self.launcher is not None)
        self.save_config_button.setEnabled(self.document is not None and self._handle is None)
        self.reload_config_button.setEnabled(self.document is not None and self._handle is None)
        self.cancel_button.setEnabled(self._handle is not None)
        self.open_log_button.setEnabled(self._log_path is not None)

    def dirty_state(self) -> DirtyState:
        dirty = bool(self.document is not None and self.document.has_unsaved_changes(self.config_editor.toPlainText()))
        return DirtyState(dirty, "Pose2Sim Config", "Config.toml 有未保存修改" if dirty else "")

    def save(self) -> bool:
        if self.document is None:
            self.config_status.setText("没有可保存的 Config.toml")
            return False
        try:
            result = self.document.save(self.config_editor.toPlainText(), "界面编辑")
        except (OSError, ConfigSyntaxError) as exc:
            self.config_status.setText(f"保存失败：{exc}")
            self._validate_editor()
            return False
        self.config_status.setText(f"配置已保存；备份：{result.backup_path}" if result.changed and result.backup_path is not None else "配置未变化")
        self._validate_editor()
        return True

    def reload(self) -> bool:
        if self.document is None:
            return False
        try:
            text = self.document.reload()
        except (OSError, ConfigSyntaxError) as exc:
            self.config_status.setText(f"重新载入失败：{exc}")
            return False
        self.config_editor.setPlainText(text)
        self.config_status.setText("已重新载入磁盘配置")
        return True

    def discard_unsaved(self) -> None:
        self.reload()

    def _current_stage(self) -> str | None:
        item = self.stage_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def run_current(self) -> bool:
        stage = self._current_stage()
        return self._start((stage,)) if stage is not None else False

    def run_selected(self) -> bool:
        selected = {str(item.data(Qt.ItemDataRole.UserRole)) for item in self.stage_list.selectedItems()}
        stages = tuple(stage for stage in GENERAL_POSE2SIM_STAGES if stage in selected)
        if not stages:
            stage = self._current_stage()
            stages = (stage,) if stage is not None else ()
        return self._start(stages)

    def run_from_current(self) -> bool:
        stage = self._current_stage()
        if stage is None:
            return False
        return self._start(GENERAL_POSE2SIM_STAGES[GENERAL_POSE2SIM_STAGES.index(stage) :])

    def _start(self, stages: tuple[str, ...]) -> bool:
        if self.project is None or self.launcher is None or not stages:
            self.run_status.setText("请先打开项目并选择阶段")
            return False
        if self.dirty_state().dirty and not self.save():
            return False
        try:
            self._handle = self.launcher.start(self.project, stages)
        except (OSError, RuntimeError, ValueError) as exc:
            self.run_status.setText(f"启动失败：{exc}")
            self._handle = None
            self._validate_editor()
            return False
        self._log_path = self.launcher.log_path_for(self._handle.task_id)
        self._log_offset = 0
        self.log_viewer.clear()
        self.run_status.setText(f"正在运行：{', '.join(stages)}")
        self._set_action_state(False)
        self._timer.start()
        return True

    def cancel_run(self) -> None:
        if self._handle is None:
            return
        self._handle.cancel()
        self.run_status.setText("正在取消 Pose2Sim 流程…")
        self.cancel_button.setEnabled(False)

    def _poll_run(self) -> None:
        self._tail_log()
        handle = self._handle
        if handle is None:
            self._timer.stop()
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self._tail_log()
        self._timer.stop()
        self._handle = None
        labels = {"succeeded": "已完成", "failed": "失败", "cancelled": "已取消"}
        self.run_status.setText(f"Pose2Sim 流程{labels[result.status]}")
        self.refresh_stages()
        self._validate_editor()
        self.pipeline_finished.emit(result)

    def _tail_log(self) -> None:
        if self._log_path is None or not self._log_path.is_file():
            return
        with self._log_path.open("rb") as handle:
            handle.seek(self._log_offset)
            data = handle.read()
            self._log_offset = handle.tell()
        if data:
            self._append_log(data.decode("utf-8", errors="replace"))

    def _append_log(self, text: str) -> None:
        lines = self.log_viewer.toPlainText().splitlines()
        lines.extend(text.splitlines())
        self.log_viewer.setPlainText("\n".join(lines[-5000:]))
        scrollbar = self.log_viewer.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def open_log(self) -> bool:
        if self._log_path is None or not self._log_path.is_file():
            self.run_status.setText("日志文件尚未生成")
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_path)))

    def closeEvent(self, event) -> None:
        self.settings.setValue("pipeline/splitter_sizes", self.splitter.sizes())
        super().closeEvent(event)
