"""Persistent application settings with explicit path validation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.external_tools.discovery import ExternalToolDiscovery

from ..layout import make_scrollable_panel


class SettingsPage(QWidget):
    settings_saved = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self._build_ui()
        self.load_settings()

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("设置")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("管理外部工具路径、视频帧缓存、二维微调步长和界面布局。空工具路径表示使用程序当前运行环境。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        form = QFormLayout()
        self.pose2sim_path = self._path_row(
            form,
            "Pose2Sim 安装文件夹",
            "settings_pose2sim_path",
            "Pose2Sim",
        )
        self.caliscope_path = self._path_row(
            form,
            "Caliscope 安装文件夹",
            "settings_caliscope_path",
            "Caliscope",
        )
        self.cache_capacity = QSpinBox()
        self.cache_capacity.setObjectName("settings_cache_capacity")
        self.cache_capacity.setRange(4, 512)
        form.addRow("视频帧缓存数量", self.cache_capacity)
        self.nudge_step = QDoubleSpinBox()
        self.nudge_step.setObjectName("settings_nudge_step")
        self.nudge_step.setRange(0.1, 100.0)
        self.nudge_step.setDecimals(2)
        form.addRow("二维点微调步长（px）", self.nudge_step)
        layout.addLayout(form)

        actions = QHBoxLayout()
        save = QPushButton("保存设置")
        save.setObjectName("settings_save_button")
        save.clicked.connect(self.save_settings)
        reset = QPushButton("恢复默认布局")
        reset.setObjectName("settings_reset_layout_button")
        reset.clicked.connect(self.reset_layout)
        actions.addWidget(save)
        actions.addWidget(reset)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status = QLabel("—")
        self.status.setObjectName("settings_status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("settings_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _path_row(
        self,
        form: QFormLayout,
        title: str,
        object_name: str,
        tool_name: str,
    ) -> QLineEdit:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setObjectName(object_name)
        edit.setPlaceholderText("留空：使用程序自带环境；也可粘贴旧的可执行文件路径")
        button = QPushButton("选择文件夹")
        button.setObjectName(f"settings_{tool_name.casefold()}_browse")
        button.clicked.connect(lambda: self._choose_path(edit, tool_name))
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        form.addRow(title, row)
        return edit

    def _choose_path(self, target: QLineEdit, tool_name: str) -> None:
        current = Path(target.text().strip()) if target.text().strip() else Path()
        start = current if current.is_dir() else current.parent if current.is_file() else Path()
        path = QFileDialog.getExistingDirectory(
            self,
            f"选择 {tool_name} 安装文件夹",
            str(start),
        )
        if path:
            target.setText(path)

    def load_settings(self) -> None:
        self.pose2sim_path.setText(self._displayed_installation("pose2sim"))
        self.caliscope_path.setText(self._displayed_installation("caliscope"))
        self.cache_capacity.setValue(self.settings.value("media/cache_capacity", 20, type=int))
        self.nudge_step.setValue(self.settings.value("correction/nudge_step", 1.0, type=float))
        self.status.setText("设置已载入")

    def save_settings(self) -> bool:
        selections = {
            "pose2sim": self.pose2sim_path.text().strip(),
            "caliscope": self.caliscope_path.text().strip(),
        }
        resolved: dict[str, tuple[str, str]] = {}
        for name, value in selections.items():
            if not value:
                continue
            try:
                installation = (
                    ExternalToolDiscovery.resolve_pose2sim(Path(value))
                    if name == "pose2sim"
                    else ExternalToolDiscovery.resolve_caliscope(Path(value))
                )
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))
                return False
            resolved[name] = (
                str(installation.installation_directory),
                str(installation.executable),
            )
        for name in selections:
            directory, executable = resolved.get(name, ("", ""))
            self.settings.setValue(f"tools/{name}_directory", directory)
            self.settings.setValue(f"tools/{name}_path", executable)
        self.settings.setValue("media/cache_capacity", self.cache_capacity.value())
        self.settings.setValue("correction/nudge_step", self.nudge_step.value())
        self.settings.sync()
        detected = "；".join(
            f"{'Pose2Sim' if name == 'pose2sim' else 'Caliscope'}：{executable}"
            for name, (_directory, executable) in resolved.items()
        )
        suffix = f"；已识别 {detected}" if detected else "；外部工具使用程序自带环境"
        self.status.setText(f"设置已保存；缓存容量将在下次启动时生效{suffix}")
        self.settings_saved.emit()
        return True

    def _displayed_installation(self, name: str) -> str:
        directory = str(self.settings.value(f"tools/{name}_directory", "")).strip()
        if directory:
            return directory
        legacy = str(self.settings.value(f"tools/{name}_path", "")).strip()
        if not legacy:
            return ""
        path = Path(legacy)
        if path.is_file():
            directory = (
                path.parent.parent
                if path.parent.name.casefold() == "scripts"
                else path.parent
            )
            return str(directory)
        return legacy

    def reset_layout(self) -> None:
        for key in (
            "workspace_splitter_sizes",
            "navigation_collapsed",
            "correction/workspace_sizes",
            "correction/view_sizes",
            "correction/view_count",
        ):
            self.settings.remove(key)
        self.settings.sync()
        self.status.setText("布局设置已恢复默认值，下次打开页面时生效")
