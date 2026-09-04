"""Synchronization inspection and manual frame-offset page."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.project.manager import ProjectManager
from app.synchronization.analyzer import SynchronizationAnalyzer
from app.synchronization.model import SynchronizationOverride
from app.synchronization.overrides import SynchronizationOverrideStore

from ..layout import make_scrollable_panel


class SynchronizationPage(QWidget):
    def __init__(self, project: ProjectManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.analyzer = SynchronizationAnalyzer()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("多相机同步")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("同步帧和原视频帧分开显示；偏移只能来自项目映射或人工确认。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("相机"))
        self.camera_selector = QComboBox()
        self.camera_selector.setObjectName("synchronization_camera_selector")
        self.camera_selector.currentTextChanged.connect(self.refresh_mapping)
        controls.addWidget(self.camera_selector)
        controls.addWidget(QLabel("同步帧"))
        self.synchronization_frame = QSpinBox()
        self.synchronization_frame.setRange(0, 100000000)
        self.synchronization_frame.setObjectName("synchronization_frame_input")
        self.synchronization_frame.valueChanged.connect(self.refresh_mapping)
        controls.addWidget(self.synchronization_frame)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("synchronization_refresh_button")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        form = QFormLayout()
        self.synchronization_frame_value = QLabel("—")
        self.synchronization_frame_value.setObjectName("synchronization_frame_value")
        self.raw_frame_value = QLabel("—")
        self.raw_frame_value.setObjectName("raw_frame_value")
        self.mapping_method = QLabel("—")
        self.mapping_source = QLabel("—")
        self.mapping_source.setWordWrap(True)
        form.addRow("同步时间轴帧", self.synchronization_frame_value)
        form.addRow("原视频时间轴帧", self.raw_frame_value)
        form.addRow("映射方法", self.mapping_method)
        form.addRow("映射来源", self.mapping_source)
        layout.addLayout(form)

        override_row = QHBoxLayout()
        override_row.addWidget(QLabel("人工 frame_delta"))
        self.override_delta = QSpinBox()
        self.override_delta.setRange(-100000, 100000)
        override_row.addWidget(self.override_delta)
        self.override_button = QPushButton("保存人工偏移")
        self.override_button.setObjectName("synchronization_override_button")
        self.override_button.clicked.connect(self.save_override)
        override_row.addWidget(self.override_button)
        override_row.addStretch(1)
        layout.addLayout(override_row)

        self.mapping_table = QTableWidget(0, 5)
        self.mapping_table.setHorizontalHeaderLabels(["相机", "同步帧", "原视频帧", "方法", "来源"])
        self.mapping_table.setObjectName("synchronization_mapping_table")
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.mapping_table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("synchronization_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_project(self, project: ProjectManager | None) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        self.camera_selector.blockSignals(True)
        self.camera_selector.clear()
        if self.project is not None:
            cameras = [
                str(item["camera_id"])
                for item in self.project.manifest.get("cameras", [])
                if isinstance(item, dict) and isinstance(item.get("camera_id"), str)
            ]
            if not cameras:
                cameras = sorted(self._cameras_from_mapping())
            self.camera_selector.addItems(cameras)
        self.camera_selector.blockSignals(False)
        self.mapping_table.setRowCount(0)
        if self.project is None:
            self.status.setText("请先打开项目")
            self.refresh_mapping()
            return
        report = self.analyzer.analyze(self.project)
        for issue in report.issues:
            self.mapping_table.insertRow(self.mapping_table.rowCount())
            row = self.mapping_table.rowCount() - 1
            self.mapping_table.setItem(row, 0, QTableWidgetItem(issue.camera or "—"))
            self.mapping_table.setItem(row, 4, QTableWidgetItem(issue.message))
        self.refresh_mapping()

    def refresh_mapping(self) -> None:
        camera = self.camera_selector.currentText()
        frame = self.synchronization_frame.value()
        self.synchronization_frame_value.setText(str(frame))
        if not camera or self.project is None:
            self.raw_frame_value.setText("无映射")
            self.mapping_method.setText("—")
            self.mapping_source.setText("—")
            return
        try:
            mapping = self.analyzer.mapping(camera, frame)
        except (KeyError, ValueError) as exc:
            self.raw_frame_value.setText("无映射")
            self.mapping_method.setText("不可用")
            self.mapping_source.setText(str(exc))
            return
        self.raw_frame_value.setText(str(mapping.source_frame))
        self.mapping_method.setText(mapping.method)
        self.mapping_source.setText(mapping.source)

    def save_override(self) -> None:
        if self.project is None or not self.camera_selector.currentText():
            self.status.setText("请先打开项目并选择相机")
            return
        mapping_path = self.project.root / "synchronization" / "mapping.json"
        override = SynchronizationOverride(
            self.camera_selector.currentText(),
            "manual",
            self.override_delta.value(),
            mapping_path if mapping_path.is_file() else None,
        )
        SynchronizationOverrideStore(self.project.root).save(override)
        self.status.setText(f"已保存 {override.camera} 的人工偏移 {override.frame_delta}")
        self.refresh()

    def _cameras_from_mapping(self) -> set[str]:
        mapping = self._load_mapping()
        cameras: set[str] = set()
        for key in ("mappings", "offsets"):
            records = mapping.get(key)
            if isinstance(records, list):
                cameras.update(
                    str(item["camera"])
                    for item in records
                    if isinstance(item, dict) and isinstance(item.get("camera"), str)
                )
        return cameras

    def _load_mapping(self) -> dict[str, object]:
        path = self.project.root / "synchronization" / "mapping.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
