"""Calibration import and per-camera diagnostic page."""

from __future__ import annotations

from pathlib import Path

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
from app.project.manager import ProjectManager


class CalibrationPage(QWidget):
    def __init__(self, project: ProjectManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.importer = CalibrationImporter()
        self.diagnostics = CalibrationDiagnostics()
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

        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setObjectName("calibration_diagnostics_list")
        layout.addWidget(self.diagnostics_list, 1)

    def set_project(self, project: ProjectManager | None) -> None:
        self.project = project
        self.refresh()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择标定文件", "", "JSON (*.json);;所有文件 (*.*)")
        if path:
            self.import_file(Path(path))

    def import_file(self, path: Path) -> None:
        if self.project is None:
            self.diagnostics_list.clear()
            self.diagnostics_list.addItem("请先打开项目")
            return
        try:
            result = self.importer.import_file(self.project, path)
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
