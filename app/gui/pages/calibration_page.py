"""Calibration import and per-camera diagnostic page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.calibration.diagnostics import CalibrationDiagnostics
from app.calibration.importer import CalibrationImporter
from app.calibration.model import CalibrationCameraReport, CalibrationPreview
from app.application.controller import ApplicationController
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest
from app.tasks.handle import TaskHandle
from app.external_tools.caliscope_settings import CaliscopeSettingsDiagnostic
from app.external_tools.launcher import ExternalProcessHandle, ExternalToolLaunchError, ExternalToolLauncher
from app.external_tools.model import build_caliscope_command


class CalibrationPage(QWidget):
    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
        *,
        controller: ApplicationController | None = None,
        settings: QSettings | None = None,
        launcher: ExternalToolLauncher | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.controller = controller
        self.settings = settings or QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self.launcher = launcher or ExternalToolLauncher()
        self.importer = CalibrationImporter()
        self.diagnostics = CalibrationDiagnostics()
        self.pending_preview: CalibrationPreview | None = None
        self._camera_reports: dict[str, CalibrationCameraReport] = {}
        self._preview_handle: TaskHandle | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(25)
        self._preview_timer.timeout.connect(self._poll_preview)
        self._caliscope_handle: ExternalProcessHandle | None = None
        self._caliscope_timer = QTimer(self)
        self._caliscope_timer.setInterval(500)
        self._caliscope_timer.timeout.connect(self._poll_caliscope)
        self._build_ui()
        if self.project is not None:
            self.caliscope_workspace.setText(str(self.project.root))
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

        tool_card = QFrame()
        tool_card.setObjectName("caliscope_tool_card")
        tool_form = QFormLayout(tool_card)
        workspace_row = QWidget()
        workspace_layout = QHBoxLayout(workspace_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.caliscope_workspace = QLineEdit()
        self.caliscope_workspace.setObjectName("caliscope_workspace")
        workspace_button = QPushButton("选择")
        workspace_button.clicked.connect(self.choose_workspace)
        workspace_layout.addWidget(self.caliscope_workspace, 1)
        workspace_layout.addWidget(workspace_button)
        tool_form.addRow("Caliscope 工作区", workspace_row)
        tool_actions = QWidget()
        tool_actions_layout = QHBoxLayout(tool_actions)
        tool_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.launch_caliscope_button = QPushButton("启动 Caliscope")
        self.launch_caliscope_button.setObjectName("calibration_launch_button")
        self.launch_caliscope_button.clicked.connect(self.launch_caliscope)
        self.convert_settings_button = QPushButton("备份并转换为 UTF-8")
        self.convert_settings_button.setObjectName("caliscope_convert_settings_button")
        self.convert_settings_button.clicked.connect(self.convert_caliscope_settings)
        tool_actions_layout.addWidget(self.launch_caliscope_button)
        tool_actions_layout.addWidget(self.convert_settings_button)
        tool_actions_layout.addStretch(1)
        tool_form.addRow("外部工具", tool_actions)
        self.caliscope_settings_status = QLabel("—")
        self.caliscope_settings_status.setWordWrap(True)
        self.caliscope_settings_status.setObjectName("caliscope_settings_status")
        self.caliscope_status = QLabel("尚未启动")
        self.caliscope_status.setWordWrap(True)
        self.caliscope_status.setObjectName("caliscope_launch_status")
        tool_form.addRow("设置诊断", self.caliscope_settings_status)
        tool_form.addRow("运行状态", self.caliscope_status)
        layout.addWidget(tool_card)

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

        details_splitter = QSplitter(Qt.Orientation.Horizontal)
        details_splitter.setObjectName("calibration_details_splitter")

        parameter_scroll = QScrollArea()
        parameter_scroll.setObjectName("calibration_parameter_scroll")
        parameter_scroll.setWidgetResizable(True)
        parameter_card = QFrame()
        parameter_card.setObjectName("calibration_parameter_card")
        parameter_form = QFormLayout(parameter_card)
        self.camera_selector = QComboBox()
        self.camera_selector.setObjectName("calibration_camera_selector")
        self.camera_selector.currentTextChanged.connect(self._show_camera_parameters)
        parameter_form.addRow("相机", self.camera_selector)
        self.image_size_value = self._parameter_label("calibration_image_size_value")
        self.matrix_value = self._parameter_label("calibration_matrix_value")
        self.distortions_value = self._parameter_label("calibration_distortions_value")
        self.rotation_value = self._parameter_label("calibration_rotation_value")
        self.translation_value = self._parameter_label("calibration_translation_value")
        self.error_value = self._parameter_label("calibration_error_value")
        parameter_form.addRow("图像尺寸", self.image_size_value)
        parameter_form.addRow("相机矩阵 K", self.matrix_value)
        parameter_form.addRow("畸变系数", self.distortions_value)
        parameter_form.addRow("旋转向量", self.rotation_value)
        parameter_form.addRow("平移向量", self.translation_value)
        parameter_form.addRow("重投影误差", self.error_value)
        parameter_scroll.setWidget(parameter_card)
        details_splitter.addWidget(parameter_scroll)

        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setObjectName("calibration_diagnostics_list")
        details_splitter.addWidget(self.diagnostics_list)
        details_splitter.setStretchFactor(0, 2)
        details_splitter.setStretchFactor(1, 1)
        layout.addWidget(details_splitter, 1)
        self.refresh_caliscope_settings_diagnostic()

    @staticmethod
    def _parameter_label(object_name: str) -> QLabel:
        label = QLabel("—")
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _format_values(values: tuple[float, ...]) -> str:
        return "[" + ", ".join(f"{value:.6f}" for value in values) + "]"

    def _set_camera_reports(self, reports: tuple[CalibrationCameraReport, ...]) -> None:
        previous = self.camera_selector.currentText()
        self._camera_reports = {report.camera_id: report for report in reports}
        self.camera_selector.blockSignals(True)
        self.camera_selector.clear()
        self.camera_selector.addItems(list(self._camera_reports))
        if previous in self._camera_reports:
            self.camera_selector.setCurrentText(previous)
        self.camera_selector.blockSignals(False)
        self._show_camera_parameters(self.camera_selector.currentText())

    def _show_camera_parameters(self, camera_id: str) -> None:
        report = self._camera_reports.get(camera_id)
        if report is None:
            for label in (
                self.image_size_value,
                self.matrix_value,
                self.distortions_value,
                self.rotation_value,
                self.translation_value,
                self.error_value,
            ):
                label.setText("—")
            return
        width, height = report.image_size
        self.image_size_value.setText(f"{width} × {height}")
        self.matrix_value.setText("\n".join(self._format_values(row) for row in report.matrix))
        self.distortions_value.setText(self._format_values(report.distortions))
        self.rotation_value.setText(self._format_values(report.rotation))
        self.translation_value.setText(self._format_values(report.translation))
        self.error_value.setText(
            "—" if report.reprojection_error is None else f"{report.reprojection_error:.6f} px"
        )

    def set_project(self, project: ProjectManager | None) -> None:
        self._preview_timer.stop()
        self._preview_handle = None
        self.pending_preview = None
        self.project = project
        self.caliscope_workspace.setText(str(project.root) if project is not None else "")
        self.refresh()

    def choose_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择 Caliscope 工作区",
            self.caliscope_workspace.text().strip(),
        )
        if selected:
            self.caliscope_workspace.setText(selected)

    def launch_caliscope(self) -> bool:
        if self._caliscope_handle is not None and self._caliscope_handle.poll() is None:
            self.caliscope_status.setText("Caliscope 正在运行，请先使用已打开的窗口")
            return False
        workspace_text = self.caliscope_workspace.text().strip()
        if not workspace_text and self.project is not None:
            workspace_text = str(self.project.root)
            self.caliscope_workspace.setText(workspace_text)
        workspace = Path(workspace_text) if workspace_text else None
        if workspace is None or not workspace.is_dir():
            self.caliscope_status.setText("请选择存在的 Caliscope 工作区")
            return False
        configured = str(self.settings.value("tools/caliscope_path", "")).strip()
        command = build_caliscope_command(workspace, configured or None)
        log_root = self.project.root if self.project is not None else workspace
        log_path = log_root / "logs" / f"caliscope-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        try:
            handle = self.launcher.start(command, workspace, log_path)
        except (ExternalToolLaunchError, OSError) as exc:
            self.caliscope_status.setText(f"启动失败：{exc}")
            return False
        self._caliscope_handle = handle
        if self.controller is not None:
            self.controller.register_resource(handle)
        self._caliscope_timer.start()
        self.caliscope_status.setText(f"已启动；日志：{log_path}")
        return True

    def _poll_caliscope(self) -> None:
        handle = self._caliscope_handle
        if handle is None:
            self._caliscope_timer.stop()
            return
        return_code = handle.poll()
        if return_code is None:
            return
        self._caliscope_timer.stop()
        self.caliscope_status.setText(
            f"Caliscope 已退出（代码 {return_code}）；日志：{handle.log_path}"
        )

    def refresh_caliscope_settings_diagnostic(self) -> None:
        path = CaliscopeSettingsDiagnostic.default_path()
        diagnostic = CaliscopeSettingsDiagnostic.inspect(path)
        self.caliscope_settings_status.setText(f"{path}：{diagnostic.message}")
        self.convert_settings_button.setEnabled(
            diagnostic.valid and diagnostic.encoding != "utf-8"
        )

    def convert_caliscope_settings(self) -> bool:
        path = CaliscopeSettingsDiagnostic.default_path()
        try:
            backup = CaliscopeSettingsDiagnostic.convert_to_utf8(path)
        except (OSError, ValueError) as exc:
            self.caliscope_settings_status.setText(f"转换失败：{exc}")
            return False
        self.refresh_caliscope_settings_diagnostic()
        self.caliscope_settings_status.setText(f"已转换为 UTF-8；备份：{backup}")
        return True

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
            self._set_camera_reports(())
            self.diagnostics_list.addItem("请先打开项目")
            return
        report = self.diagnostics.analyze(self.project)
        self.active_path.setText(str(report.active_path) if report.active_path is not None else "—")
        self.fingerprint.setText(report.fingerprint or "—")
        self.camera_summary.setText(", ".join(report.camera_ids) or "—")
        self._set_camera_reports(report.cameras)
        if not report.issues:
            self.diagnostics_list.addItem("诊断通过：未发现问题")
        for issue in report.issues:
            self.diagnostics_list.addItem(f"[{issue.severity}] {issue.message}")
