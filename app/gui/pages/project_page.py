"""Project creation, opening, recent-project, and migration status page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.project.manager import ProjectManager

from ..layout import make_scrollable_panel


class ProjectPage(QWidget):
    open_requested = Signal(object)
    create_requested = Signal(object, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("项目工作区")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel("打开已有分析项目，或创建一个保留原始素材、修正历史和处理状态的新项目。")
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("project_current_card")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel("当前项目"))
        self.current_project = QLabel("未打开项目")
        self.current_project.setObjectName("project_current_name")
        self.current_project.setStyleSheet("font-size: 18px; font-weight: 650; color: #ffffff;")
        self.current_project.setWordWrap(True)
        card_layout.addWidget(self.current_project)
        self.project_path = QLabel("选择一个包含 manifest.json 的目录")
        self.project_path.setWordWrap(True)
        self.project_path.setStyleSheet("color: #8295a3;")
        card_layout.addWidget(self.project_path)
        self.recovery_status = QLabel("迁移与恢复状态：等待打开项目")
        self.recovery_status.setWordWrap(True)
        card_layout.addWidget(self.recovery_status)
        layout.addWidget(card)

        actions = QHBoxLayout()
        self.open_button = QPushButton("打开项目")
        self.open_button.setObjectName("project_open_button")
        self.open_button.clicked.connect(self.choose_project)
        self.create_button = QPushButton("新建项目")
        self.create_button.setObjectName("project_create_button")
        self.create_button.clicked.connect(self.choose_new_project)
        actions.addWidget(self.open_button)
        actions.addWidget(self.create_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        layout.addWidget(QLabel("最近项目"))
        self.recent_projects = QListWidget()
        self.recent_projects.setObjectName("project_recent_list")
        self.recent_projects.itemDoubleClicked.connect(
            lambda item: self.open_requested.emit(
                Path(item.data(Qt.ItemDataRole.UserRole))
            )
        )
        layout.addWidget(self.recent_projects, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._load_recent()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(make_scrollable_panel(body))

    def choose_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "打开 Motion Analysis Studio 项目")
        if directory:
            self.open_requested.emit(Path(directory))

    def choose_new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择新项目目录")
        if not directory:
            return
        name, accepted = QInputDialog.getText(self, "新建项目", "项目名称")
        if accepted and name.strip():
            self.create_requested.emit(Path(directory), name.strip())

    def set_project(self, project: ProjectManager) -> None:
        name = str(project.manifest.get("name", project.root.name))
        self.current_project.setText(name)
        self.project_path.setText(str(project.root))
        states: list[str] = []
        if project.migrated:
            states.append("已从旧版本迁移")
        if project.recovered_transactions:
            states.append(f"已恢复 {len(project.recovered_transactions)} 个未完成事务")
        self.recovery_status.setText(
            "迁移与恢复状态：" + ("；".join(states) if states else "项目结构正常")
        )
        self.status.setText("项目已加载")
        self._remember(project.root)

    def show_error(self, message: str) -> None:
        self.status.setText(f"打开失败：{message}")

    def _load_recent(self) -> None:
        self.recent_projects.clear()
        values = self.settings.value("recent_projects", [])
        if isinstance(values, str):
            values = [values]
        for value in values if isinstance(values, list) else []:
            path = Path(str(value))
            item_text = path.name or str(path)
            self.recent_projects.addItem(item_text)
            self.recent_projects.item(self.recent_projects.count() - 1).setData(
                Qt.ItemDataRole.UserRole,
                str(path),
            )

    def _remember(self, path: Path) -> None:
        values = self.settings.value("recent_projects", [])
        if isinstance(values, str):
            values = [values]
        recent = [str(path)] + [str(value) for value in values if str(value) != str(path)]
        self.settings.setValue("recent_projects", recent[:8])
        self._load_recent()
