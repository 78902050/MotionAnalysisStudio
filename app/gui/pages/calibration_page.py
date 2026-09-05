"""Calibration import and per-camera diagnostic page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.calibration.diagnostics import CalibrationDiagnostics
from app.calibration.importer import CalibrationImporter
from app.calibration.model import CalibrationPreview
from app.application.controller import ApplicationController
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest
from app.tasks.handle import TaskHandle


class CalibrationPage(QWidget):
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
        self.importer = CalibrationImporter()
        self.diagnostics = CalibrationDiagnostics()
        self.pending_preview: CalibrationPreview | None = None
        self._preview_handle: TaskHandle | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(25)
        self._preview_timer.timeout.connect(self._poll_preview)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("相机标定")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("导入外部标定文件的项目副本，并查看当前激活文件和逐相机诊断。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        actions = QHBoxLayout()
        self.import_button = QPushButton("导入标定文件")
        self.import_button.setObjectName("calibration_import_button")
        self.import_button.clicked.connect(self.choose_file)
        actions.addWidget(self.import_button)
        self.activate_button = QPushButton("激活预览标定")
        self.activate_button.setObjectName("calibration_activate_button")
        self.activate_button.setEnabled(False)
        self.activate_button.clicked.connect(self.activate_preview)
        actions.addWidget(self.activate_button)
        self.refresh_button = QPushButton("刷新诊断")
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        card = QFrame()
        card.setObjectName("calibration_active_card")
        form = QFormLayout(card)
        self.active_path = QLabel("—")
        self.active_path.setObjectName("calibration_active_path")
        self.fingerprint = QLabel("—")
        self.fingerprint.setObjectName("calibration_fingerprint")
        self.camera_summary = QLabel("—")
        form.addRow("当前激活文件", self.active_path)
        form.addRow("内容指纹", self.fingerprint)
        form.addRow("相机", self.camera_summary)
        layout.addWidget(card)

        preview_card = QFrame()
        preview_card.setObjectName("calibration_preview_card")
        preview_form = QFormLayout(preview_card)
        self.preview_source = QLabel("—")
        self.preview_source.setObjectName("calibration_preview_source")
        self.preview_cameras = QLabel("—")
        self.preview_cameras.setObjectName("calibration_preview_cameras")
        self.preview_differences = QLabel("—")
        self.preview_differences.setWordWrap(True)
        self.preview_differences.setObjectName("calibration_preview_differences")
        self.preview_status = QLabel("尚未预览标定文件")
        self.preview_status.setObjectName("calibration_preview_status")
        self.preview_status.setWordWrap(True)
        preview_form.addRow("待激活来源", self.preview_source)
        preview_form.addRow("待激活相机", self.preview_cameras)
        preview_form.addRow("参数差异", self.preview_differences)
        preview_form.addRow("预览状态", self.preview_status)
        layout.addWidget(preview_card)

        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setObjectName("calibration_diagnostics_list")
        layout.addWidget(self.diagnostics_list, 1)

    def set_project(self, project: ProjectManager | None) -> None:
        self._preview_timer.stop()
        self._preview_handle = None
        self.pending_preview = None
        self.project = project
        self.refresh()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择标定文件",
            "",
            "Caliscope 标定 (*.toml *.json);;所有文件 (*.*)",
        )
        if path:
            self.preview_file(Path(path))

    def preview_file(self, path: Path) -> None:
        if self.project is None:
            self.preview_status.setText("请先打开项目")
            return
        if (
            self.controller is not None
            and self.controller.current_project is self.project
        ):
            request = TaskRequest(
                str(self.project.manifest["project_id"]),
                self.controller.generation,
                "calibration-preview",
                {"path": str(path)},
            )
            project = self.project

            def work(token):
                token.raise_if_cancelled()
                preview = self.importer.preview(project, path)
                token.raise_if_cancelled()
                return preview

            self.pending_preview = None
            self.activate_button.setEnabled(False)
            self.preview_status.setText("正在后台解析并验证标定文件…")
            self._preview_handle = self.controller.start_task(request, work)
            self._preview_timer.start()
            return
        try:
            preview = self.importer.preview(self.project, path)
        except (OSError, ValueError) as exc:
            self.pending_preview = None
            self.activate_button.setEnabled(False)
            self.preview_status.setText(f"预览失败：{exc}")
            return
        self._show_preview(preview)

    def _poll_preview(self) -> None:
        handle = self._preview_handle
        if handle is None:
            self._preview_timer.stop()
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self._preview_timer.stop()
        self._preview_handle = None
        project_id = str(self.project.manifest["project_id"]) if self.project is not None else ""
        generation = self.controller.generation if self.controller is not None else -1
        if result.project_id != project_id or result.generation != generation:
            return
        if result.status != "succeeded" or not isinstance(result.value, CalibrationPreview):
            self.preview_status.setText(f"预览失败：{result.error or result.status}")
            return
        self._show_preview(result.value)

    def _show_preview(self, preview: CalibrationPreview) -> None:
        self.pending_preview = preview
        blocked = any(issue.severity == "blocking" for issue in preview.issues)
        self.preview_source.setText(f"{preview.source_format} · {preview.source_path}")
        self.preview_cameras.setText(", ".join(preview.camera_ids))
        difference_text = (
            "参数等价，无需激活" if preview.equivalent else "\n".join(preview.differences)
        )
        if preview.issues:
            difference_text += "\n" + "\n".join(
                f"[{issue.severity}] {issue.message}" for issue in preview.issues
            )
        self.preview_differences.setText(difference_text)
        self.activate_button.setEnabled(not preview.equivalent and not blocked)
        self.preview_status.setText(
            "存在阻断诊断，不能激活"
            if blocked
            else "内容等价，当前标定保持不变"
            if preview.equivalent
            else f"等待人工确认激活（{len(preview.differences)} 项差异）"
        )

    def activate_preview(self) -> None:
        if self.project is None or self.pending_preview is None:
            self.preview_status.setText("没有可激活的标定预览")
            return
        try:
            result = self.importer.activate(self.project, self.pending_preview)
        except (OSError, ValueError) as exc:
            self.preview_status.setText(f"激活失败：{exc}")
            return
        self.pending_preview = None
        self.activate_button.setEnabled(False)
        self.refresh()
        self.preview_status.setText(
            "已激活新标定" if result.changed else "参数等价，当前标定保持不变"
        )

    def import_file(self, path: Path) -> None:
        if self.project is None:
            self.diagnostics_list.clear()
            self.diagnostics_list.addItem("请先打开项目")
            return
        try:
            preview = self.importer.preview(self.project, path)
            result = self.importer.activate(self.project, preview)
        except (OSError, ValueError) as exc:
            self.diagnostics_list.clear()
            self.diagnostics_list.addItem(f"导入失败：{exc}")
            return
        self.diagnostics_list.clear()
        self.diagnostics_list.addItem("内容未变化，保持当前激活文件" if not result.changed else "已导入并更新当前激活文件")
        self.refresh()

    def refresh(self) -> None:
        self.diagnostics_list.clear()
        if self.project is None:
            self.pending_preview = None
            self.activate_button.setEnabled(False)
            self.active_path.setText("未打开项目")
            self.fingerprint.setText("—")
            self.camera_summary.setText("—")
            self.diagnostics_list.addItem("请先打开项目")
            return
        report = self.diagnostics.analyze(self.project)
        self.active_path.setText(str(report.active_path) if report.active_path is not None else "—")
        self.fingerprint.setText(report.fingerprint or "—")
        self.camera_summary.setText(", ".join(report.camera_ids) or "—")
        if not report.issues:
            self.diagnostics_list.addItem("诊断通过：未发现问题")
        for issue in report.issues:
            self.diagnostics_list.addItem(f"[{issue.severity}] {issue.message}")
