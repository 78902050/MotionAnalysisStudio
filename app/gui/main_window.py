"""Resizable desktop shell for the motion-analysis workspace."""

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Qt, Signal, Slot
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
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.application.controller import ApplicationController
from app.application.correction_rerun_launcher import CorrectionRerunLauncher
from app.application.quality_correction_service import QualityCorrectionService
from app.domain.addresses import CorrectionTarget, FrameAddress
from app.media.frame_provider import MultiViewFrameProvider
from app.project.manager import ProjectManager
from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter
from app.quality.audit import QualityAuditService
from app.tasks.base import TaskRequest
from app.tasks.handle import TaskHandle

from .layout import make_resizable_splitter, make_scrollable_panel
from .pages.analysis_page import AnalysisPage
from .pages.association_page import AssociationPage
from .pages.calibration_page import CalibrationPage
from .pages.comparison_page import ComparisonPage
from .pages.correction_page import CorrectionPage
from .pages.events_page import EventsPage
from .pages.media_page import MediaPage
from .pages.project_page import ProjectPage
from .pages.quality_2d_page import Quality2DPage
from .pages.quality_3d_page import Quality3DPage
from .pages.synchronization_page import SynchronizationPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
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


class _ExistingResultScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = Path(root)

    @Slot()
    def run(self) -> None:
        try:
            candidates = ExistingResultDiscovery().scan(self.root)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(candidates)


class MainWindow(QMainWindow):
    def __init__(
        self,
        parent: QWidget | None = None,
        controller: ApplicationController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Motion Analysis Studio")
        self.setMinimumSize(480, 360)
        self.resize(1120, 720)
        self.settings = QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self.controller = controller or ApplicationController()
        self._correction_rerun_launcher = CorrectionRerunLauncher(self.controller)
        if not self.controller.has_correction_rerun_handler():
            self.controller.set_correction_rerun_handler(self._correction_rerun_launcher)
        self.project: ProjectManager | None = self.controller.current_project
        self.quality_correction_service: QualityCorrectionService | None = None
        cache_capacity = self.settings.value("media/cache_capacity", 20, type=int)
        self.frame_provider = MultiViewFrameProvider(
            cache_capacity=max(4, min(512, cache_capacity))
        )
        self.controller.register_resource(self.frame_provider)
        self.unsaved_changes = False
        self._discovery_thread: QThread | None = None
        self._discovery_worker: _ExistingResultScanWorker | None = None
        self.initial_quality_handle: TaskHandle | None = None
        self._quality_scan_timer = QTimer(self)
        self._quality_scan_timer.setInterval(100)
        self._quality_scan_timer.timeout.connect(self._poll_initial_quality_scan)
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
            page = (
                ProjectPage()
                if page_id == "project"
                else MediaPage(controller=self.controller)
                if page_id == "media"
                else SettingsPage(settings=self.settings)
                if page_id == "settings"
                else TasksPage(self.controller.supervisor)
                if page_id == "tasks"
                else CalibrationPage(controller=self.controller)
                if page_id == "calibration"
                else SynchronizationPage(controller=self.controller)
                if page_id == "synchronization"
                else Quality2DPage()
                if page_id == "quality_2d"
                else CorrectionPage(provider=self.frame_provider, controller=self.controller)
                if page_id == "correction_2d"
                else AssociationPage(controller=self.controller)
                if page_id == "association"
                else AnalysisPage()
                if page_id == "analysis"
                else EventsPage()
                if page_id == "events"
                else ComparisonPage(controller=self.controller)
                if page_id == "comparison"
                else Quality3DPage()
                if page_id == "quality_3d"
                else self._build_page(page_id, label)
            )
            self._pages[page_id] = page
            self.page_stack.addWidget(page)
        project_page = self._pages["project"]
        assert isinstance(project_page, ProjectPage)
        project_page.open_requested.connect(self.open_project_path)
        project_page.create_requested.connect(self.create_project)
        project_page.import_existing_requested.connect(self.import_existing_path)
        project_page.scan_parent_requested.connect(self.scan_existing_parent)
        project_page.register_candidate_requested.connect(self.register_existing_candidate)
        project_page.register_all_requested.connect(self.register_all_existing)
        correction_page = self._pages["correction_2d"]
        assert isinstance(correction_page, CorrectionPage)
        self.controller.register_editor("correction_2d", correction_page)
        correction_page.frame_requested.connect(self._open_correction_frame)
        for page_id in ("quality_2d", "quality_3d"):
            quality_page = self._pages[page_id]
            assert isinstance(quality_page, (Quality2DPage, Quality3DPage))
            quality_page.target_requested.connect(self._open_correction_target)
        self.workspace_splitter = make_resizable_splitter(self.navigation, self.page_stack)
        self.workspace_splitter.setObjectName("workspace_splitter")
        root_layout.addWidget(self.workspace_splitter, 1)

        self.task_strip = TaskStatusStrip()
        root_layout.addWidget(self.task_strip)
        self.controller.add_task_listener(self.task_strip.set_handle)
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
        icon_names = (
            QStyle.StandardPixmap.SP_DirHomeIcon,
            QStyle.StandardPixmap.SP_FileIcon,
            QStyle.StandardPixmap.SP_DialogApplyButton,
            QStyle.StandardPixmap.SP_BrowserReload,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_ArrowRight,
            QStyle.StandardPixmap.SP_DialogYesButton,
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_MediaPlay,
            QStyle.StandardPixmap.SP_MediaSeekForward,
            QStyle.StandardPixmap.SP_FileDialogContentsView,
            QStyle.StandardPixmap.SP_MessageBoxInformation,
            QStyle.StandardPixmap.SP_FileDialogInfoView,
        )
        for index, (page_id, label) in enumerate(PAGE_LABELS):
            item = QListWidgetItem(self.style().standardIcon(icon_names[index]), label)
            item.setData(Qt.ItemDataRole.UserRole, page_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, label)
            item.setToolTip(label)
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
            "association": "诊断人物轨迹、查看候选并人工确认语义关联。",
            "analysis": "计算位置、速度、加速度和角度等可追溯运动学指标。",
            "events": "按规则检测动作事件、构建周期并保留人工调整历史。",
            "comparison": "明确选择项目、人物和试次，按帧、时间或事件生成可复现对比报告。",
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
        page = self._pages[page_id]
        if self.project is not None and isinstance(page, (Quality2DPage, Quality3DPage)):
            page.set_project(self.project)
        self.page_stack.setCurrentWidget(page)
        for row in range(self.navigation_list.count()):
            item = self.navigation_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == page_id:
                self.navigation_list.setCurrentRow(row)
                break
        return True

    def open_project(
        self,
        project: ProjectManager,
        *,
        dirty_decision: str | None = None,
    ) -> bool:
        decision = dirty_decision
        if decision is None:
            decision = self._ask_dirty_decision() if self.controller.dirty_states() else "discard"
        if not self.controller.open_project(project, dirty_decision=decision):
            message = self.controller.last_error or "未切换项目"
            self.statusBar().showMessage(message)
            return False
        self.project = project
        self.quality_correction_service = QualityCorrectionService(project)
        self.project_label.setText(str(project.manifest.get("name", project.root.name)))
        stages = project.manifest.get("stages", {})
        active_stage = next(
            (name for name, record in stages.items() if isinstance(record, dict) and record.get("status") == "running"),
            "未开始",
        )
        self.stage_label.setText(f"阶段：{active_stage}")
        calibration_page = self._pages.get("calibration")
        if isinstance(calibration_page, CalibrationPage):
            calibration_page.set_project(project)
        media_page = self._pages.get("media")
        if isinstance(media_page, MediaPage):
            media_page.set_project(project)
        synchronization_page = self._pages.get("synchronization")
        if isinstance(synchronization_page, SynchronizationPage):
            synchronization_page.set_project(project)
        correction_page = self._pages.get("correction_2d")
        if isinstance(correction_page, CorrectionPage):
            correction_page.clear_project_context()
            correction_page.set_timeline_range(
                *self.quality_correction_service.timeline_bounds()
            )
            cameras = []
            for record in project.manifest.get("cameras", []):
                if not isinstance(record, dict):
                    continue
                camera_id = record.get("camera_id")
                if isinstance(camera_id, str) and camera_id.strip():
                    cameras.append(camera_id)
            correction_page.set_cameras(cameras)
            videos: dict[str, Path] = {}
            for record in project.manifest.get("cameras", []):
                if not isinstance(record, dict):
                    continue
                camera_id = record.get("camera_id")
                path_value = record.get("video_path")
                if isinstance(camera_id, str) and isinstance(path_value, str) and path_value:
                    candidate = Path(path_value)
                    if not candidate.is_absolute():
                        candidate = project.root / candidate
                    videos[camera_id] = candidate
            self.frame_provider.set_project(str(project.manifest["project_id"]), videos)
        for page_id in ("quality_2d", "quality_3d"):
            quality_page = self._pages.get(page_id)
            if isinstance(quality_page, (Quality2DPage, Quality3DPage)):
                quality_page.set_project(project)
        association_page = self._pages.get("association")
        if isinstance(association_page, AssociationPage):
            association_page.set_project(project)
        analysis_page = self._pages.get("analysis")
        if isinstance(analysis_page, AnalysisPage):
            analysis_page.set_project(project)
        events_page = self._pages.get("events")
        if isinstance(events_page, EventsPage):
            events_page.set_project(project)
        comparison_page = self._pages.get("comparison")
        if isinstance(comparison_page, ComparisonPage):
            comparison_page.set_project(project)
        project_page = self._pages.get("project")
        if isinstance(project_page, ProjectPage):
            project_page.set_project(project)
        self._start_initial_quality_scan_if_needed(project)
        self.statusBar().showMessage(f"已打开项目：{project.root}")
        return True

    def _start_initial_quality_scan_if_needed(self, project: ProjectManager) -> None:
        self.initial_quality_handle = None
        imported = project.manifest.get("imported_artifacts")
        if not isinstance(imported, dict) or not imported.get("pose_2d_files"):
            return
        if project.path_for("quality_report").is_file():
            return
        request = TaskRequest(
            str(project.manifest["project_id"]),
            self.controller.generation,
            "初始质量扫描",
            {"project_root": str(project.root)},
        )

        def work(token):
            token.raise_if_cancelled()
            service = QualityAuditService()
            report = service.analyze(project)
            token.raise_if_cancelled()
            service.save(report)
            return report

        self.initial_quality_handle = self.controller.start_task(request, work)
        self._quality_scan_timer.start()
        self.statusBar().showMessage("正在后台生成初始质量报告…")

    @Slot()
    def _poll_initial_quality_scan(self) -> None:
        handle = self.initial_quality_handle
        if handle is None:
            self._quality_scan_timer.stop()
            return
        snapshot = self.controller.supervisor.snapshot(handle.task_id)
        if snapshot.status not in {"completed", "failed", "cancelled"}:
            return
        self._quality_scan_timer.stop()
        result = handle.wait(0)
        project = self.project
        if (
            project is None
            or not self.controller.supervisor.accepts_result(
                result,
                str(project.manifest["project_id"]),
                self.controller.generation,
            )
        ):
            return
        if result.status == "succeeded":
            for page_id in ("quality_2d", "quality_3d"):
                page = self._pages.get(page_id)
                if isinstance(page, (Quality2DPage, Quality3DPage)):
                    page.set_project(project)
            self.statusBar().showMessage("初始质量报告已生成")
        elif result.status == "failed":
            self.statusBar().showMessage(f"初始质量扫描失败：{result.error}")

    def _open_correction_target(self, target: CorrectionTarget) -> bool:
        service = self.quality_correction_service
        correction_page = self._pages.get("correction_2d")
        if service is None or not isinstance(correction_page, CorrectionPage):
            self.statusBar().showMessage("请先打开质量报告所属项目")
            return False
        if correction_page.dirty_state().dirty:
            decision = self._ask_dirty_decision()
            if decision == "cancel":
                self.statusBar().showMessage("已取消切换修正目标")
                return False
            if decision == "save":
                if not correction_page.save():
                    self.statusBar().showMessage("保存失败，仍停留在原修正目标")
                    return False
            else:
                correction_page.discard_unsaved()
        resolution = service.resolve_target(target)
        session = service.create_session(resolution) if resolution.can_edit else None
        correction_page.open_resolution(resolution, session)
        cameras = tuple(
            str(record["camera_id"])
            for record in self.project.manifest.get("cameras", [])
            if isinstance(record, dict)
            and isinstance(record.get("camera_id"), str)
            and record["camera_id"].strip()
        ) if self.project is not None else ()
        if resolution.synchronized_frame is not None:
            addresses, failures = service.raw_view_addresses(
                resolution.synchronized_frame,
                cameras,
            )
            correction_page.set_view_addresses(addresses, failures)
        self.navigate("correction_2d")
        if resolution.blocker:
            self.statusBar().showMessage(resolution.blocker)
        return True

    def _open_correction_frame(self, synchronized_frame: int) -> None:
        correction_page = self._pages.get("correction_2d")
        if not isinstance(correction_page, CorrectionPage):
            return
        resolution = correction_page.resolution
        target = resolution.report_target if resolution is not None else None
        if target is None:
            return
        previous_frame = resolution.synchronized_frame
        opened = self._open_correction_target(
            CorrectionTarget(
                FrameAddress(
                    target.address.camera,
                    target.address.timeline,
                    int(synchronized_frame),
                ),
                target.person,
                target.keypoint,
            )
        )
        if not opened and previous_frame is not None:
            correction_page.timeline.setValue(previous_frame)

    def open_project_path(self, path: Path | str) -> bool:
        project_page = self._pages.get("project")
        try:
            project = ProjectManager.open(Path(path))
        except (OSError, ValueError) as exc:
            if isinstance(project_page, ProjectPage):
                project_page.show_error(str(exc))
            return False
        return self.open_project(project)

    def create_project(self, path: Path | str, name: str) -> bool:
        project_page = self._pages.get("project")
        try:
            project = ProjectManager.create(Path(path), name)
        except (OSError, ValueError) as exc:
            if isinstance(project_page, ProjectPage):
                project_page.show_error(str(exc))
            return False
        return self.open_project(project)

    def import_existing_path(self, path: Path | str) -> bool:
        project_page = self._pages.get("project")
        try:
            candidate = ExistingResultDiscovery().discover_one(Path(path))
            project = ExistingResultImporter().register(candidate)
        except (OSError, ValueError) as exc:
            if isinstance(project_page, ProjectPage):
                project_page.show_error(str(exc))
            return False
        return self.open_project(project)

    def scan_existing_parent(self, path: Path | str) -> bool:
        project_page = self._pages.get("project")
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            if isinstance(project_page, ProjectPage):
                project_page.status.setText("已有目录扫描正在进行")
            return False
        if isinstance(project_page, ProjectPage):
            project_page.status.setText("正在后台扫描已处理试次…")
        thread = QThread(self)
        worker = _ExistingResultScanWorker(Path(path))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._existing_scan_finished)
        worker.failed.connect(self._existing_scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._existing_scan_thread_finished)
        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()
        return True

    @Slot(object)
    def _existing_scan_finished(self, candidates: object) -> None:
        project_page = self._pages.get("project")
        if isinstance(project_page, ProjectPage):
            project_page.set_candidates(tuple(candidates))

    @Slot(str)
    def _existing_scan_failed(self, reason: str) -> None:
        project_page = self._pages.get("project")
        if isinstance(project_page, ProjectPage):
            project_page.show_error(f"扫描失败：{reason}")

    @Slot()
    def _existing_scan_thread_finished(self) -> None:
        if self._discovery_worker is not None:
            self._discovery_worker.deleteLater()
        if self._discovery_thread is not None:
            self._discovery_thread.deleteLater()
        self._discovery_worker = None
        self._discovery_thread = None

    def register_existing_candidate(self, candidate: object) -> bool:
        project_page = self._pages.get("project")
        try:
            project = ExistingResultImporter().register(candidate)
        except (OSError, ValueError) as exc:
            if isinstance(project_page, ProjectPage):
                project_page.show_error(str(exc))
            return False
        return self.open_project(project)

    def register_all_existing(self, candidates: object) -> int:
        project_page = self._pages.get("project")
        registered: list[ProjectManager] = []
        failures: list[str] = []
        for candidate in tuple(candidates):
            try:
                registered.append(ExistingResultImporter().register(candidate))
            except (OSError, ValueError) as exc:
                failures.append(f"{candidate.root.name}: {exc}")
        if registered:
            self.open_project(registered[0])
        if isinstance(project_page, ProjectPage):
            message = f"已登记 {len(registered)} 个试次"
            if failures:
                message += f"；失败 {len(failures)} 个：{'；'.join(failures)}"
            project_page.status.setText(message)
        return len(registered)

    @property
    def current_page(self) -> QWidget:
        return self.page_stack.currentWidget()

    def set_unsaved_changes(self, value: bool) -> None:
        self.unsaved_changes = value
        self.save_label.setText("保存状态：有未保存更改" if value else "保存状态：无更改")

    def request_close_with_unsaved_guard(self) -> bool:
        dirty = self.controller.dirty_states()
        if not dirty and not self.unsaved_changes:
            return self.controller.shutdown(dirty_decision="discard")
        decision = self._ask_dirty_decision()
        if decision == "cancel":
            return False
        if self.unsaved_changes and not dirty:
            if decision == "save":
                self.statusBar().showMessage("没有可执行保存的编辑服务")
                return False
            self.set_unsaved_changes(False)
        closed = self.controller.shutdown(dirty_decision=decision)
        if not closed:
            self.statusBar().showMessage(self.controller.last_error or "无法关闭")
        return closed

    def _ask_dirty_decision(self) -> str:
        box = QMessageBox(self)
        box.setWindowTitle("未保存更改")
        box.setText("当前页面有未保存更改。")
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return "save"
        if box.clickedButton() is discard:
            return "discard"
        assert box.clickedButton() is cancel or box.clickedButton() is None
        return "cancel"

    def toggle_navigation(self) -> None:
        collapsed = self.navigation.width() > 60
        self._apply_navigation_collapsed(collapsed)
        self.settings.setValue("navigation_collapsed", collapsed)

    def _apply_navigation_collapsed(self, collapsed: bool) -> None:
        self.navigation.setMinimumWidth(48 if collapsed else 180)
        self.navigation.setMaximumWidth(48 if collapsed else 280)
        for row in range(self.navigation_list.count()):
            item = self.navigation_list.item(row)
            label = str(item.data(Qt.ItemDataRole.UserRole + 1))
            item.setText("" if collapsed else label)
            item.setToolTip(label)

    def _restore_layout(self) -> None:
        sizes = self.settings.value("workspace_splitter_sizes")
        if isinstance(sizes, list) and sizes:
            self.workspace_splitter.setSizes([int(size) for size in sizes])
        if self.settings.value("navigation_collapsed", False, type=bool):
            self._apply_navigation_collapsed(True)

    def closeEvent(self, event) -> None:
        if not self.request_close_with_unsaved_guard():
            event.ignore()
            return
        self.settings.setValue("workspace_splitter_sizes", self.workspace_splitter.sizes())
        association_page = self._pages.get("association")
        if isinstance(association_page, AssociationPage):
            association_page.close()
        media_page = self._pages.get("media")
        if isinstance(media_page, MediaPage):
            media_page.close()
        analysis_page = self._pages.get("analysis")
        if isinstance(analysis_page, AnalysisPage):
            analysis_page.close()
        events_page = self._pages.get("events")
        if isinstance(events_page, EventsPage):
            events_page.close()
        comparison_page = self._pages.get("comparison")
        if isinstance(comparison_page, ComparisonPage):
            comparison_page.close()
        if self._discovery_thread is not None and self._discovery_thread.isRunning():
            self._discovery_thread.quit()
            self._discovery_thread.wait(5000)
        event.accept()
