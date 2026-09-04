"""Resizable desktop shell for the motion-analysis workspace."""

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.project.manager import ProjectManager

from .layout import make_resizable_splitter, make_scrollable_panel
from .pages.correction_page import CorrectionPage
from .style import apply_style
from .task_center import TaskStatusStrip

PAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("project", "项目"),
    ("media", "视频素材"),
    ("calibration", "相机标定"),
    ("synchronization", "同步"),
    ("quality_2d", "二维质检"),
    ("correction_2d", "二维修正"),
    ("association", "多人关联"),
    ("quality_3d", "三维质检"),
    ("analysis", "运动学"),
    ("events", "事件周期"),
    ("comparison", "对比报告"),
    ("tasks", "任务与日志"),
    ("settings", "设置"),
)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Motion Analysis Studio")
        self.setMinimumSize(480, 360)
        self.resize(1120, 720)
        self.project: ProjectManager | None = None
        self.unsaved_changes = False
        self.settings = QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self.page_ids = tuple(page_id for page_id, _ in PAGE_LABELS)
        self._pages: dict[str, QWidget] = {}

        application = self.windowHandle().screen().virtualSiblingAt(0, 0) if self.windowHandle() else None
        del application
        self._build_ui()
        self._restore_layout()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 0)
        root_layout.setSpacing(8)
        root_layout.addWidget(self._build_project_bar())

        self.navigation = self._build_navigation()
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("page_stack")
        for page_id, label in PAGE_LABELS:
            page = CorrectionPage() if page_id == "correction_2d" else self._build_page(page_id, label)
            self._pages[page_id] = page
            self.page_stack.addWidget(page)
        self.workspace_splitter = make_resizable_splitter(self.navigation, self.page_stack)
        self.workspace_splitter.setObjectName("workspace_splitter")
        root_layout.addWidget(self.workspace_splitter, 1)

        self.task_strip = TaskStatusStrip()
        root_layout.addWidget(self.task_strip)
        self.setCentralWidget(root)
        self.statusBar().showMessage("就绪")
        self.navigate("project")

        collapse_action = QAction("折叠导航", self)
        collapse_action.setShortcut("Ctrl+Shift+L")
        collapse_action.triggered.connect(self.toggle_navigation)
        self.addAction(collapse_action)
        apply_style(self._application())

    def _build_project_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("project_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 9, 12, 9)
        eyebrow = QLabel("MOTION ANALYSIS")
        eyebrow.setObjectName("eyebrow")
        self.project_label = QLabel("未打开项目")
        self.project_label.setObjectName("project_label")
        self.stage_label = QLabel("阶段：未开始")
        self.save_label = QLabel("保存状态：无更改")
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(eyebrow)
        layout.addWidget(self.project_label)
        layout.addSpacing(18)
        layout.addWidget(self.stage_label)
        layout.addStretch(1)
        layout.addWidget(self.save_label)
        layout.addWidget(settings_button)
        return bar

    def _build_navigation(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("side_panel")
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        self.navigation_list = QListWidget()
        self.navigation_list.setObjectName("navigation_list")
        for page_id, label in PAGE_LABELS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, page_id)
            self.navigation_list.addItem(item)
        self.navigation_list.currentRowChanged.connect(self._navigate_from_row)
        layout.addWidget(self.navigation_list, 1)
        return panel

    def _build_page(self, page_id: str, label: str) -> QWidget:
        body = QWidget()
        body.setObjectName(f"page_{page_id}")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel(label)
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel(self._description_for(page_id))
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("当前项目", QLabel("等待项目打开"))
        form.addRow("当前状态", QLabel("未开始"))
        form.addRow("提示", QLabel("详细数据将在对应阶段完成后显示。"))
        layout.addLayout(form)
        actions = QHBoxLayout()
        actions.addWidget(QPushButton("打开项目"))
        actions.addWidget(QPushButton("查看日志"))
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return make_scrollable_panel(body)

    @staticmethod
    def _description_for(page_id: str) -> str:
        descriptions = {
            "quality_2d": "按相机、帧、人物和关节点查看二维质量问题。",
            "correction_2d": "在可调分栏中确认二维点位，保存前保留可恢复历史。",
            "quality_3d": "查看重投影误差、有效点率、缺失率和覆盖区间。",
            "calibration": "查看当前标定输入和相机质量诊断。",
            "synchronization": "查看同步帧与原视频帧的映射关系。",
        }
        return descriptions.get(page_id, "管理当前项目的阶段数据和操作。")

    def _application(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()

    def _navigate_from_row(self, row: int) -> None:
        if row < 0:
            return
        page_id = self.navigation_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.page_stack.setCurrentWidget(self._pages[page_id])

    def navigate(self, page_id: str) -> bool:
        if page_id not in self._pages:
            return False
        self.page_stack.setCurrentWidget(self._pages[page_id])
        matches = self.navigation_list.findItems(
            next(label for candidate, label in PAGE_LABELS if candidate == page_id),
            Qt.MatchFlag.MatchExactly,
        )
        if matches:
            self.navigation_list.setCurrentItem(matches[0])
        return True

    def open_project(self, project: ProjectManager) -> None:
        self.project = project
        self.project_label.setText(str(project.manifest.get("name", project.root.name)))
        stages = project.manifest.get("stages", {})
        active_stage = next(
            (name for name, record in stages.items() if isinstance(record, dict) and record.get("status") == "running"),
            "未开始",
        )
        self.stage_label.setText(f"阶段：{active_stage}")
        self.statusBar().showMessage(f"已打开项目：{project.root}")

    @property
    def current_page(self) -> QWidget:
        return self.page_stack.currentWidget()

    def set_unsaved_changes(self, value: bool) -> None:
        self.unsaved_changes = value
        self.save_label.setText("保存状态：有未保存更改" if value else "保存状态：无更改")

    def request_close_with_unsaved_guard(self) -> bool:
        if not self.unsaved_changes:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("未保存更改")
        box.setText("当前页面有未保存更改。")
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return True
        return box.clickedButton() is discard

    def toggle_navigation(self) -> None:
        collapsed = self.navigation.width() > 60
        self.navigation.setMinimumWidth(48 if collapsed else 180)
        self.navigation.setMaximumWidth(48 if collapsed else 280)
        self.settings.setValue("navigation_collapsed", collapsed)

    def _restore_layout(self) -> None:
        sizes = self.settings.value("workspace_splitter_sizes")
        if isinstance(sizes, list) and sizes:
            self.workspace_splitter.setSizes([int(size) for size in sizes])
        if self.settings.value("navigation_collapsed", False, type=bool):
            self.navigation.setMinimumWidth(48)
            self.navigation.setMaximumWidth(48)

    def closeEvent(self, event) -> None:
        if not self.request_close_with_unsaved_guard():
            event.ignore()
            return
        self.settings.setValue("workspace_splitter_sizes", self.workspace_splitter.sizes())
        event.accept()
