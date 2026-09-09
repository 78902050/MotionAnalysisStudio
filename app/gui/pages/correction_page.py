"""Resizable 2D correction workspace for dense issue-review sessions."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.domain.addresses import CorrectionTarget
from app.domain.issues import QualityIssue
from app.application.dirty_state import DirtyState
from app.visualization.skeleton import SkeletonTopologyRepository, skeleton_edge_side

from ..layout import make_resizable_splitter, make_scrollable_panel
from ..theme import palette_for_application

if TYPE_CHECKING:
    from app.application.quality_correction_service import CorrectionResolution


def _quality_issue_label(issue: QualityIssue) -> str:
    if issue.target is None:
        return f"不可定位 · {issue.message}"
    frame_label = "原始帧" if issue.target.timeline == "raw" else "帧"
    person_label = (
        f"人物 {issue.person.raw_person_index + 1}"
        if issue.person is not None and issue.person.raw_person_index is not None
        else issue.person.project_person_id
        if issue.person is not None
        else "人物未知"
    )
    keypoint_label = issue.keypoint.keypoint_name if issue.keypoint is not None else "关节点未知"
    confidence = issue.evidence.get("confidence")
    measurement = (
        f" · 置信度 {float(confidence):.3f}"
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else ""
    )
    return (
        f"{issue.target.camera} · {frame_label} {issue.target.frame} · "
        f"{person_label} · {keypoint_label}{measurement}\n{issue.message}"
    )


class CorrectionCanvas(QWidget):
    """Image-space canvas with a draggable selected keypoint."""

    point_moved = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._selected_point: QPointF | None = None
        self._points: dict[str, tuple[float, float, float]] = {}
        self._edges: tuple[tuple[str, str], ...] = ()
        self._data_width = 0.0
        self._data_height = 0.0
        self._explicit_extent = False
        self._zoom = 1.0
        self._dragging_point = False
        self._panning = False
        self._last_mouse: QPointF | None = None
        self._pan = QPointF()
        self.setMinimumSize(120, 100)
        self.setMouseTracking(True)

    @property
    def has_frame(self) -> bool:
        return not self._image.isNull()

    @property
    def has_coordinate_space(self) -> bool:
        width, height = self._space_size()
        return width > 0 and height > 0

    @property
    def data_extent(self) -> tuple[int, int]:
        width, height = self._space_size()
        return round(width), round(height)

    def set_data_extent(self, width: int | float, height: int | float) -> None:
        width = float(width)
        height = float(height)
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            raise ValueError("姿态坐标空间尺寸必须是正有限数")
        self._data_width = width
        self._data_height = height
        self._explicit_extent = True
        self.update()

    @property
    def point_count(self) -> int:
        return len(self._points)

    @property
    def edge_count(self) -> int:
        return sum(self._edge_is_visible(edge) for edge in self._edges)

    def set_frame(self, image: object) -> None:
        if isinstance(image, QImage):
            converted = image.copy()
        else:
            shape = getattr(image, "shape", None)
            strides = getattr(image, "strides", None)
            data = getattr(image, "data", None)
            if not isinstance(shape, tuple) or len(shape) != 3 or shape[2] != 3 or strides is None:
                raise ValueError("视频帧必须是 H×W×3 的 BGR 图像")
            converted = QImage(
                data,
                int(shape[1]),
                int(shape[0]),
                int(strides[0]),
                QImage.Format.Format_BGR888,
            ).copy()
        self._image = converted
        self._data_width = float(converted.width())
        self._data_height = float(converted.height())
        self.update()

    def set_selected_point(self, x: float, y: float) -> None:
        self._selected_point = QPointF(float(x), float(y))
        self.update()

    def set_pose_points(
        self,
        points: dict[str, tuple[float, float, float]],
        edges: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._points = dict(points)
        self._edges = tuple(edges)
        if self._image.isNull() and points and not self._explicit_extent:
            finite_points = [
                (float(x), float(y))
                for x, y, _confidence in points.values()
                if math.isfinite(float(x))
                and math.isfinite(float(y))
                and float(x) >= 0
                and float(y) >= 0
            ]
            if finite_points:
                maximum_x = max(point[0] for point in finite_points)
                maximum_y = max(point[1] for point in finite_points)
                self._data_width = max(640.0, maximum_x * 1.05 + 1.0)
                self._data_height = max(480.0, maximum_y * 1.05 + 1.0)
        self.update()

    def clear(self) -> None:
        self._image = QImage()
        self._selected_point = None
        self._points.clear()
        self._edges = ()
        self._data_width = 0.0
        self._data_height = 0.0
        self._explicit_extent = False
        self._zoom = 1.0
        self._dragging_point = False
        self._panning = False
        self._last_mouse = None
        self._pan = QPointF()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        palette = palette_for_application()
        painter.fillRect(self.rect(), QColor(palette.canvas))
        target = self._image_rect()
        if not self._image.isNull():
            painter.drawImage(target, self._image)
        elif not target.isEmpty():
            painter.fillRect(target, QColor(palette.recessed))
            painter.setPen(QPen(QColor(palette.border), 1))
            painter.drawRect(target)
        if not target.isEmpty():
            edge_colors = {
                "left": QColor(palette.canvas_left),
                "right": QColor(palette.canvas_right),
                "center": QColor(palette.canvas_center),
            }
            for edge in self._edges:
                if not self._edge_is_visible(edge):
                    continue
                painter.setPen(QPen(edge_colors[skeleton_edge_side(edge)], 2.4))
                left = self._points[edge[0]]
                right = self._points[edge[1]]
                painter.drawLine(
                    self._image_to_widget(QPointF(left[0], left[1])),
                    self._image_to_widget(QPointF(right[0], right[1])),
                )
            point_color = QColor(palette.accent)
            point_fill = QColor(palette.accent)
            point_fill.setAlpha(125)
            painter.setPen(QPen(point_color, 1))
            painter.setBrush(point_fill)
            for x, y, confidence in self._points.values():
                if confidence <= 0:
                    continue
                painter.drawEllipse(self._image_to_widget(QPointF(x, y)), 3, 3)
        if self._selected_point is not None and not target.isEmpty():
            point = self._image_to_widget(self._selected_point)
            selected_fill = QColor(palette.warning)
            selected_fill.setAlpha(80)
            painter.setPen(QPen(QColor(palette.warning), 2))
            painter.setBrush(selected_fill)
            painter.drawEllipse(point, 7, 7)
            painter.drawLine(point + QPointF(-11, 0), point + QPointF(11, 0))
            painter.drawLine(point + QPointF(0, -11), point + QPointF(0, 11))

    def _edge_is_visible(self, edge: tuple[str, str]) -> bool:
        if edge[0] not in self._points or edge[1] not in self._points:
            return False
        for name in edge:
            x, y, confidence = self._points[name]
            if confidence <= 0 or not math.isfinite(x) or not math.isfinite(y):
                return False
        return True

    def mousePressEvent(self, event) -> None:
        self._dragging_point = False
        if event.button() == Qt.MouseButton.LeftButton and self._selected_point is not None and self.has_coordinate_space:
            selected = self._image_to_widget(self._selected_point)
            delta = event.position() - selected
            self._dragging_point = delta.x() ** 2 + delta.y() ** 2 <= 16 ** 2
        if not self._dragging_point and event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        }:
            self._panning = True
            self._last_mouse = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging_point:
            point = self._widget_to_image(event.position())
            width, height = self._space_size()
            x = min(max(point.x(), 0.0), max(0.0, width - 1.0))
            y = min(max(point.y(), 0.0), max(0.0, height - 1.0))
            self.set_selected_point(x, y)
            self.point_moved.emit(x, y)
        elif self._panning and self._last_mouse is not None:
            self._pan += event.position() - self._last_mouse
            self._last_mouse = event.position()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() in {Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton}:
            self._dragging_point = False
            self._panning = False
            self._last_mouse = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        anchor = event.position()
        image_point = self._widget_to_image(anchor) if self.has_coordinate_space else None
        self._zoom = min(
            8.0,
            max(
                0.25,
                self._zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15),
            ),
        )
        if image_point is not None:
            self._pan += anchor - self._image_to_widget(image_point)
        self.update()
        event.accept()

    def _image_rect(self) -> QRectF:
        data_width, data_height = self._space_size()
        if data_width <= 0 or data_height <= 0 or self.width() <= 0 or self.height() <= 0:
            return QRectF()
        scale = min(self.width() / data_width, self.height() / data_height) * self._zoom
        width = data_width * scale
        height = data_height * scale
        return QRectF(
            (self.width() - width) / 2 + self._pan.x(),
            (self.height() - height) / 2 + self._pan.y(),
            width,
            height,
        )

    def _image_to_widget(self, point: QPointF) -> QPointF:
        target = self._image_rect()
        data_width, data_height = self._space_size()
        return QPointF(
            target.left() + point.x() * target.width() / data_width,
            target.top() + point.y() * target.height() / data_height,
        )

    def _widget_to_image(self, point: QPointF) -> QPointF:
        target = self._image_rect()
        data_width, data_height = self._space_size()
        return QPointF(
            (point.x() - target.left()) * data_width / target.width(),
            (point.y() - target.top()) * data_height / target.height(),
        )

    def _space_size(self) -> tuple[float, float]:
        if not self._image.isNull():
            return float(self._image.width()), float(self._image.height())
        return self._data_width, self._data_height


class CorrectionPage(QWidget):
    frame_requested = Signal(int)
    browse_requested = Signal(str, int, int, int)
    quality_issue_requested = Signal(object)
    _ISSUES_PER_PAGE = 200

    def __init__(
        self,
        provider: Any = None,
        session: Any = None,
        controller: Any = None,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.session = session
        self.controller = controller
        self.settings = (
            settings
            if settings is not None
            else QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        )
        self.resolution: CorrectionResolution | None = None
        self._view_cards: list[QFrame] = []
        self._view_labels: list[QLabel] = []
        self._canvases: list[CorrectionCanvas] = []
        self._view_row_splitters: list[QSplitter] = []
        self._expected_frames: dict[str, int] = {}
        self._camera_names: list[str] = []
        self._camera_extents: dict[str, tuple[int, int]] = {}
        self._pose_inventory: dict[str, tuple[int, ...]] = {}
        self._quality_issues: tuple[QualityIssue, ...] = ()
        self._quality_issue_page = 0
        self._suppress_browse = False
        self._view_addresses: dict[str, FrameAddress] = {}
        self._view_failures: dict[str, str] = {}
        self._pending_skeleton_camera: str | None = None
        self._topologies = SkeletonTopologyRepository()
        self._playback_waiting_for_video = False
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)
        self._play_timer.timeout.connect(self._play_next_frame)
        self._build_ui()
        if self.provider is not None:
            self.provider.frame_ready.connect(self._on_frame_ready)
            self.provider.frame_failed.connect(self._on_frame_failed)
        self.clear_project_context()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)
        root_layout.addWidget(self._build_header())

        self.workspace_splitter = make_resizable_splitter(
            self._build_issue_panel(),
            self._build_view_panel(),
            self._build_details_panel(),
        )
        self.workspace_splitter.setObjectName("correction_workspace_splitter")
        self.workspace_splitter.setSizes([220, 560, 280])
        root_layout.addWidget(self.workspace_splitter, 1)
        root_layout.addWidget(self._build_action_bar())
        self._install_shortcuts()
        self._restore_layout()
        self.workspace_splitter.splitterMoved.connect(lambda *_: self.persist_layout())
        self.views_splitter.splitterMoved.connect(lambda *_: self.persist_layout())
        for row in self._view_row_splitters:
            row.splitterMoved.connect(lambda *_: self.persist_layout())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("correction_header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 4, 8, 4)
        title = QLabel("二维修正")
        title.setProperty("uiRole", "pageTitle")
        subtitle = QLabel("人工确认点位后再保存；同步帧与原视频帧分开显示")
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        self.session_status = QLabel("未打开修正会话")
        self.session_status.setObjectName("correction_session_status")
        layout.addWidget(self.session_status)
        return header

    def _build_issue_panel(self) -> QScrollArea:
        panel = QFrame()
        panel.setObjectName("correction_issue_panel")
        panel.setMinimumHeight(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("问题队列")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)
        self.issue_filter = QComboBox()
        self.issue_filter.addItems(["全部问题", "待处理", "已处理", "已延期", "已忽略"])
        self.issue_filter.setObjectName("correction_issue_filter")
        self.issue_filter.currentIndexChanged.connect(self._reset_issue_page)
        layout.addWidget(self.issue_filter)
        self.issue_list = QListWidget()
        self.issue_list.setObjectName("correction_issue_list")
        self.issue_list.itemClicked.connect(self._request_quality_issue)
        layout.addWidget(self.issue_list, 1)
        queue_pagination = QHBoxLayout()
        self.previous_queue_page_button = QPushButton("上一页")
        self.previous_queue_page_button.setObjectName("correction_previous_issue_page")
        self.next_queue_page_button = QPushButton("下一页")
        self.next_queue_page_button.setObjectName("correction_next_issue_page")
        self.issue_page_label = QLabel("第 0/0 页")
        self.issue_page_label.setObjectName("correction_issue_page")
        self.previous_queue_page_button.clicked.connect(
            lambda: self._change_issue_page(-1)
        )
        self.next_queue_page_button.clicked.connect(lambda: self._change_issue_page(1))
        queue_pagination.addWidget(self.previous_queue_page_button)
        queue_pagination.addWidget(self.issue_page_label)
        queue_pagination.addWidget(self.next_queue_page_button)
        layout.addLayout(queue_pagination)
        navigation = QHBoxLayout()
        self.previous_button = QPushButton("上一问题")
        self.previous_button.setObjectName("correction_previous_button")
        self.next_button = QPushButton("下一问题")
        self.next_button.setObjectName("correction_next_button")
        self.previous_button.clicked.connect(self._previous_issue)
        self.next_button.clicked.connect(self._next_issue)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        layout.addLayout(navigation)
        self.disposition_label = QLabel("状态：待处理")
        self.disposition_label.setWordWrap(True)
        layout.addWidget(self.disposition_label)
        area = make_scrollable_panel(panel)
        area.setObjectName("correction_issue_scroll")
        return area

    def _build_view_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("correction_view_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("视图"))
        self.view_count = QComboBox()
        self.view_count.addItem("1 路", 1)
        self.view_count.addItem("2 路", 2)
        self.view_count.addItem("4 路", 4)
        self.view_count.setCurrentIndex(1)
        self.view_count.currentIndexChanged.connect(lambda _: self.set_view_count(self.view_count.currentData()))
        controls.addWidget(self.view_count)
        controls.addWidget(QLabel("显示相机"))
        self.camera_selector = QComboBox()
        self.camera_selector.addItem("请先打开项目")
        self.camera_selector.setObjectName("correction_camera_selector")
        self.camera_selector.currentTextChanged.connect(self._select_camera)
        controls.addWidget(self.camera_selector)
        controls.addStretch(1)
        self.view_hint = QLabel("视频读取在后台线程进行")
        self.view_hint.setProperty("uiRole", "accent")
        controls.addWidget(self.view_hint)
        layout.addLayout(controls)

        self.views_splitter = QSplitter(Qt.Orientation.Vertical)
        self.views_splitter.setObjectName("correction_views_splitter")
        self.views_splitter.setChildrenCollapsible(False)
        self.views_splitter.setHandleWidth(5)
        for row_index in range(2):
            row = QSplitter(Qt.Orientation.Horizontal)
            row.setObjectName(f"correction_view_row_{row_index + 1}")
            row.setChildrenCollapsible(False)
            row.setHandleWidth(5)
            self.views_splitter.addWidget(row)
            self._view_row_splitters.append(row)
        for index in range(4):
            card = QFrame()
            card.setObjectName(f"correction_view_{index + 1}")
            card.setProperty("camera", "")
            card.setMinimumWidth(120)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card_layout = QVBoxLayout(card)
            label = QLabel(f"视图 {index + 1}\n等待原视频帧")
            label.setObjectName(f"correction_view_label_{index + 1}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setProperty("uiRole", "muted")
            canvas = CorrectionCanvas()
            canvas.setObjectName(f"correction_canvas_{index + 1}")
            canvas.point_moved.connect(
                lambda x, y, view_index=index: self._canvas_point_moved(view_index, x, y)
            )
            card_layout.addWidget(label)
            card_layout.addWidget(canvas, 1)
            self._view_row_splitters[index // 2].addWidget(card)
            self._view_cards.append(card)
            self._view_labels.append(label)
            self._canvases.append(canvas)
        layout.addWidget(self.views_splitter, 1)
        self._apply_view_layout(2)
        return panel

    def _build_details_panel(self) -> QScrollArea:
        details = QWidget()
        details.setMinimumHeight(640)
        details.setObjectName("correction_details_content")
        layout = QVBoxLayout(details)
        layout.setContentsMargins(10, 6, 10, 6)
        title = QLabel("当前目标")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.current_camera = QLabel("—")
        self.synchronized_frame = QLabel("—")
        self.raw_frame = QLabel("—")
        self.person_value = QLabel("—")
        self.keypoint_value = QLabel("—")
        self.person_selector = QComboBox()
        self.person_selector.setObjectName("correction_person_selector")
        self.person_selector.addItem("人物 0", 0)
        self.person_selector.currentIndexChanged.connect(self._browse_person_changed)
        self.keypoint_selector = QComboBox()
        self.keypoint_selector.setObjectName("correction_keypoint_selector")
        self.keypoint_selector.addItem("index-000", 0)
        self.keypoint_selector.currentIndexChanged.connect(self._emit_browse_request)
        self.x_value = QSpinBox()
        self.x_value.setRange(-100000, 100000)
        self.y_value = QSpinBox()
        self.y_value.setRange(-100000, 100000)
        self.confidence_value = QSlider(Qt.Orientation.Horizontal)
        self.confidence_value.setRange(0, 100)
        self.confidence_value.setValue(100)
        self.note_value = QLineEdit()
        self.note_value.setPlaceholderText("填写本次确认说明")
        form.addRow("当前相机", self.current_camera)
        form.addRow("同步帧", self.synchronized_frame)
        form.addRow("原视频帧", self.raw_frame)
        form.addRow("人物", self.person_value)
        form.addRow("关节点", self.keypoint_value)
        form.addRow("浏览人物", self.person_selector)
        form.addRow("浏览关节点", self.keypoint_selector)
        form.addRow("X", self.x_value)
        form.addRow("Y", self.y_value)
        form.addRow("置信度", self.confidence_value)
        form.addRow("备注", self.note_value)
        layout.addLayout(form)
        layout.addWidget(QLabel("坐标修改只在人工确认并保存后写入工作 JSON。"))
        layout.addStretch(1)
        area = make_scrollable_panel(details)
        area.setObjectName("correction_details_scroll")
        return area

    def _build_action_bar(self) -> QScrollArea:
        bar = QFrame()
        bar.setObjectName("correction_action_bar")
        bar.setMinimumWidth(820)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 5, 6, 5)
        self.previous_frame_button = QPushButton("上一帧")
        self.next_frame_button = QPushButton("下一帧")
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("correction_play_button")
        self.play_button.setEnabled(False)
        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("correction_undo_button")
        self.redo_button = QPushButton("重做")
        self.redo_button.setObjectName("correction_redo_button")
        self.reset_button = QPushButton("恢复当前帧")
        self.reset_button.setObjectName("correction_reset_button")
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("correction_save_button")
        self.save_rerun_button = QPushButton("保存并重跑")
        self.save_rerun_button.setObjectName("correction_save_rerun_button")
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.setObjectName("correction_timeline")
        for widget in (
            self.previous_frame_button,
            self.next_frame_button,
            self.play_button,
            self.undo_button,
            self.redo_button,
            self.reset_button,
        ):
            layout.addWidget(widget)
        layout.addWidget(self.timeline, 1)
        layout.addWidget(self.save_button)
        layout.addWidget(self.save_rerun_button)
        self.undo_button.clicked.connect(self.undo_selected)
        self.redo_button.clicked.connect(self.redo_selected)
        self.reset_button.clicked.connect(self.reset_selected_frame)
        self.save_button.clicked.connect(self.save)
        self.save_rerun_button.clicked.connect(self.save_and_rerun)
        self.previous_frame_button.clicked.connect(lambda: self._request_relative_frame(-1))
        self.next_frame_button.clicked.connect(lambda: self._request_relative_frame(1))
        self.play_button.clicked.connect(self.toggle_playback)
        self.timeline.sliderPressed.connect(self.stop_playback)
        self.timeline.sliderReleased.connect(self._timeline_released)
        area = make_scrollable_panel(bar)
        area.setObjectName("correction_action_scroll")
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setMinimumHeight(bar.sizeHint().height() + 10)
        area.setMaximumHeight(bar.sizeHint().height() + 26)
        return area

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_button.click)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
        QShortcut(QKeySequence("R"), self, activated=self.reset_button.click)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.nudge_selected(-1, 0))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.nudge_selected(1, 0))
        QShortcut(
            QKeySequence(Qt.KeyboardModifier.ShiftModifier | Qt.Key.Key_Left),
            self,
            activated=lambda: self.nudge_selected(-5, 0),
        )
        QShortcut(
            QKeySequence(Qt.KeyboardModifier.ShiftModifier | Qt.Key.Key_Right),
            self,
            activated=lambda: self.nudge_selected(5, 0),
        )

    def set_view_count(self, count: int) -> None:
        count = int(count)
        if count not in {1, 2, 4}:
            raise ValueError("view count must be 1, 2 or 4")
        self._apply_view_layout(count)
        self.settings.setValue("correction/view_count", count)
        if self._view_addresses or self._view_failures:
            self._request_visible_frames()

    def _apply_view_layout(self, count: int) -> None:
        for index, card in enumerate(self._view_cards):
            card.setVisible(index < count)
        if self._view_row_splitters:
            self._view_row_splitters[0].setVisible(count >= 1)
            self._view_row_splitters[1].setVisible(count == 4)
            self.views_splitter.setSizes([1, 1] if count == 4 else [1, 0])
            self._view_row_splitters[0].setSizes([1, 1] if count >= 2 else [1, 0])
            self._view_row_splitters[1].setSizes([1, 1])

    def set_timeline_range(self, first_frame: int, last_frame: int) -> None:
        first = max(0, int(first_frame))
        last = max(first, int(last_frame))
        self.timeline.setRange(first, last)

    def _request_relative_frame(self, offset: int) -> None:
        self.stop_playback()
        frames = self._pose_inventory.get(self.camera_selector.currentText(), ())
        if frames:
            current = self.timeline.value()
            if offset < 0:
                requested = next((frame for frame in reversed(frames) if frame < current), frames[0])
            else:
                requested = next((frame for frame in frames if frame > current), frames[-1])
            self.timeline.setValue(requested)
            self._emit_browse_request()
            return
        requested = min(
            self.timeline.maximum(),
            max(self.timeline.minimum(), self.timeline.value() + int(offset)),
        )
        self.frame_requested.emit(requested)

    def _timeline_released(self) -> None:
        if self._pose_inventory:
            self._emit_browse_request()
        else:
            self.frame_requested.emit(self.timeline.value())

    def toggle_playback(self) -> None:
        frames = self._pose_inventory.get(self.camera_selector.currentText(), ())
        if self._play_timer.isActive():
            self.stop_playback()
            return
        if not frames:
            self.play_button.setEnabled(False)
            return
        if self.timeline.value() >= frames[-1]:
            self.timeline.setValue(frames[0])
            self._emit_browse_request()
        self._playback_waiting_for_video = False
        self._play_timer.start()
        self.play_button.setText("暂停")

    def stop_playback(self) -> None:
        self._play_timer.stop()
        self._playback_waiting_for_video = False
        if hasattr(self, "play_button"):
            self.play_button.setText("播放")

    def _play_next_frame(self) -> None:
        if self._playback_waiting_for_video:
            return
        frames = self._pose_inventory.get(self.camera_selector.currentText(), ())
        if not frames:
            self.stop_playback()
            return
        current = self.timeline.value()
        next_frame = next((frame for frame in frames if frame > current), None)
        if next_frame is None:
            self.stop_playback()
            return
        self._playback_waiting_for_video = self.provider is not None
        self.timeline.setValue(next_frame)
        self._emit_browse_request()

    def set_pose_inventory(self, inventory: dict[str, tuple[int, ...] | list[int]]) -> None:
        self.stop_playback()
        normalized: dict[str, tuple[int, ...]] = {}
        for camera, frames in inventory.items():
            if not isinstance(camera, str) or not camera.strip():
                continue
            values = tuple(
                sorted(
                    {
                        int(frame)
                        for frame in frames
                        if isinstance(frame, int) and not isinstance(frame, bool) and frame >= 0
                    }
                )
            )
            if values:
                normalized[camera] = values
        self._pose_inventory = normalized
        self.play_button.setEnabled(bool(normalized))
        self.set_cameras(tuple(normalized))
        if normalized:
            self._apply_pose_camera(self.camera_selector.currentText(), emit=True)

    def _apply_pose_camera(self, camera: str, *, emit: bool) -> None:
        frames = self._pose_inventory.get(camera, ())
        if not frames:
            return
        self.set_timeline_range(frames[0], frames[-1])
        if self.timeline.value() not in frames:
            self.timeline.setValue(frames[0])
        if emit:
            self._emit_browse_request()

    def _browse_person_changed(self) -> None:
        self._emit_browse_request()

    def _emit_browse_request(self) -> None:
        if self._suppress_browse:
            return
        camera = self.camera_selector.currentText()
        frames = self._pose_inventory.get(camera, ())
        if not frames:
            return
        requested = self.timeline.value()
        frame = min(frames, key=lambda candidate: abs(candidate - requested))
        if frame != requested:
            self.timeline.setValue(frame)
        person = self.person_selector.currentData()
        keypoint = self.keypoint_selector.currentData()
        self.browse_requested.emit(
            camera,
            frame,
            int(person) if isinstance(person, int) else 0,
            int(keypoint) if isinstance(keypoint, int) else 0,
        )

    def set_cameras(self, cameras: list[str] | tuple[str, ...]) -> None:
        names = [camera for camera in cameras if isinstance(camera, str) and camera.strip()]
        self._camera_names = names
        self.camera_selector.blockSignals(True)
        self.camera_selector.clear()
        self.camera_selector.addItems(names or ["请先打开项目"])
        selected_camera = self.settings.value("correction/selected_camera", "")
        if isinstance(selected_camera, str):
            selected_index = self.camera_selector.findText(selected_camera)
            if selected_index >= 0:
                self.camera_selector.setCurrentIndex(selected_index)
        self.camera_selector.blockSignals(False)
        if not names:
            for index, card in enumerate(self._view_cards):
                card.setProperty("camera", "")
                self._view_labels[index].setText(f"视图 {index + 1} · 等待原视频帧")
                self._canvases[index].clear()
            return
        self._select_camera(self.camera_selector.currentText(), persist=False)

    def set_camera_extents(self, extents: dict[str, tuple[int, int]]) -> None:
        self._camera_extents = dict(extents)
        for index, card in enumerate(self._view_cards):
            camera = str(card.property("camera") or "")
            extent = self._camera_extents.get(camera)
            if extent is not None:
                self._canvases[index].set_data_extent(*extent)

    def _select_camera(self, camera: str, *, persist: bool = True) -> None:
        self.stop_playback()
        if camera not in self._camera_names:
            return
        if persist:
            self.settings.setValue("correction/selected_camera", camera)
        ordered = [camera, *(name for name in self._camera_names if name != camera)]
        for index, card in enumerate(self._view_cards):
            bound_camera = ordered[index] if index < len(ordered) else ""
            card.setProperty("camera", bound_camera)
            self._view_labels[index].setText(
                f"{bound_camera or f'视图 {index + 1}'} · 等待原视频帧"
            )
            self._canvases[index].clear()
            extent = self._camera_extents.get(bound_camera)
            if extent is not None:
                self._canvases[index].set_data_extent(*extent)
        if self._view_addresses or self._view_failures:
            self._request_visible_frames()
        self._apply_pose_camera(camera, emit=persist)

    def set_view_addresses(
        self,
        addresses: dict[str, FrameAddress],
        failures: dict[str, str] | None = None,
    ) -> None:
        failures = failures or {}
        self._view_addresses = dict(addresses)
        self._view_failures = dict(failures)
        self._expected_frames = {
            camera: address.frame for camera, address in addresses.items()
        }
        self._request_visible_frames()
        pending_camera = self._pending_skeleton_camera
        if pending_camera and pending_camera not in addresses:
            if pending_camera in failures:
                self._clear_camera_canvas(pending_camera)
            self._present_pending_skeleton(pending_camera)

    def refresh_video_frames(self) -> None:
        """Request the current visible frames after video bindings change."""
        self._request_visible_frames()

    def _request_visible_frames(self) -> None:
        for index, card in enumerate(self._view_cards):
            camera = str(card.property("camera") or "")
            if camera in self._view_failures:
                self._view_labels[index].setText(
                    f"{camera} · {self._view_failures[camera]}"
                )
                continue
            address = self._view_addresses.get(camera)
            if address is not None and self.provider is not None:
                self._view_labels[index].setText(
                    self._video_status(camera, f"正在读取帧 {address.frame}")
                )
                self.provider.request(address)

    def _video_status(self, camera: str, status: str) -> str:
        source_for = getattr(self.provider, "source_for", None)
        source = source_for(camera) if callable(source_for) else None
        source_label = getattr(source, "display_kind", "视频")
        return f"{camera} · {source_label} · {status}"

    def clear_project_context(self) -> None:
        self.stop_playback()
        self.session = None
        self.resolution = None
        self._expected_frames.clear()
        self._view_addresses.clear()
        self._view_failures.clear()
        self._pending_skeleton_camera = None
        self.current_camera.setText("—")
        self.synchronized_frame.setText("—")
        self.raw_frame.setText("—")
        self.person_value.setText("—")
        self.keypoint_value.setText("—")
        self.x_value.setValue(0)
        self.y_value.setValue(0)
        self.confidence_value.setValue(0)
        self.set_quality_issues(())
        self.person_selector.clear()
        self.person_selector.addItem("人物 0", 0)
        self.keypoint_selector.clear()
        self.keypoint_selector.addItem("index-000", 0)
        for index, canvas in enumerate(self._canvases):
            canvas.clear()
            camera = str(self._view_cards[index].property("camera") or "")
            self._view_labels[index].setText(
                f"{camera or f'视图 {index + 1}'} · 等待原视频帧"
            )
        for widget in (
            self.x_value,
            self.y_value,
            self.confidence_value,
            self.note_value,
            self.undo_button,
            self.redo_button,
            self.reset_button,
            self.save_button,
            self.save_rerun_button,
        ):
            widget.setEnabled(False)
        self.session_status.setText("未打开修正会话")

    def set_target(self, target: CorrectionTarget) -> None:
        self.current_camera.setText(target.address.camera)
        self.synchronized_frame.setText(str(target.address.frame))
        self.raw_frame.setText("等待映射")
        self.person_value.setText(target.person.project_person_id)
        self.keypoint_value.setText(target.keypoint.keypoint_name)

    def set_quality_issues(self, issues: tuple[QualityIssue, ...] | list[QualityIssue]) -> None:
        self._quality_issues = tuple(issues)
        self._quality_issue_page = 0
        self._fill_issue_queue()

    def _filtered_quality_issues(self) -> tuple[QualityIssue, ...]:
        dispositions = {
            "待处理": "pending",
            "已处理": "handled",
            "已延期": "deferred",
            "已忽略": "ignored",
        }
        requested = dispositions.get(self.issue_filter.currentText())
        if requested is None:
            return self._quality_issues
        return tuple(
            issue for issue in self._quality_issues if issue.disposition == requested
        )

    def _fill_issue_queue(self) -> None:
        issues = self._filtered_quality_issues()
        page_count = (len(issues) + self._ISSUES_PER_PAGE - 1) // self._ISSUES_PER_PAGE
        if page_count:
            self._quality_issue_page = min(self._quality_issue_page, page_count - 1)
        else:
            self._quality_issue_page = 0
        start = self._quality_issue_page * self._ISSUES_PER_PAGE
        visible = issues[start : start + self._ISSUES_PER_PAGE]
        self.issue_list.blockSignals(True)
        self.issue_list.clear()
        if visible:
            for issue in visible:
                item = QListWidgetItem(_quality_issue_label(issue))
                item.setData(Qt.ItemDataRole.UserRole, issue)
                item.setToolTip(issue.message)
                self.issue_list.addItem(item)
        else:
            self.issue_list.addItem("暂无质量问题")
        self.issue_list.blockSignals(False)
        current = self._quality_issue_page + 1 if page_count else 0
        self.issue_page_label.setText(
            f"第 {current}/{page_count} 页 · 共 {len(issues)} 项"
        )
        self.previous_queue_page_button.setEnabled(self._quality_issue_page > 0)
        self.next_queue_page_button.setEnabled(
            page_count > 0 and self._quality_issue_page < page_count - 1
        )

    def _reset_issue_page(self, *_ignored: object) -> None:
        self._quality_issue_page = 0
        self._fill_issue_queue()

    def _change_issue_page(self, offset: int) -> None:
        issues = self._filtered_quality_issues()
        page_count = (len(issues) + self._ISSUES_PER_PAGE - 1) // self._ISSUES_PER_PAGE
        requested = min(max(0, self._quality_issue_page + offset), max(0, page_count - 1))
        if requested == self._quality_issue_page:
            return
        self._quality_issue_page = requested
        self._fill_issue_queue()

    def _request_quality_issue(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(issue, QualityIssue):
            self.quality_issue_requested.emit(issue)

    def _select_quality_issue(self, issue_id: str) -> None:
        issues = self._filtered_quality_issues()
        index = next(
            (position for position, issue in enumerate(issues) if issue.issue_id == issue_id),
            None,
        )
        if index is None:
            return
        self._quality_issue_page = index // self._ISSUES_PER_PAGE
        self._fill_issue_queue()
        row = index % self._ISSUES_PER_PAGE
        item = self.issue_list.item(row)
        if item is not None:
            self.issue_list.setCurrentItem(item)

    def open_resolution(
        self,
        resolution: CorrectionResolution,
        session: Any,
    ) -> None:
        self._suppress_browse = True
        self.resolution = resolution
        self.session = session
        if resolution.edit_target is not None:
            self._expected_frames = {
                resolution.edit_target.address.camera: resolution.edit_target.address.frame
            }
        target = resolution.report_target or resolution.edit_target
        if target is not None:
            self.set_target(target)
            if self.camera_selector.findText(target.address.camera) >= 0:
                self.camera_selector.setCurrentText(target.address.camera)
        self.synchronized_frame.setText(
            str(resolution.synchronized_frame)
            if resolution.synchronized_frame is not None
            else "—"
        )
        self.raw_frame.setText(
            str(resolution.raw_frame) if resolution.raw_frame is not None else "—"
        )
        pose_frames = (
            self._pose_inventory.get(resolution.edit_target.address.camera, ())
            if resolution.edit_target is not None
            else ()
        )
        timeline_frame = (
            resolution.raw_frame
            if pose_frames and resolution.raw_frame is not None
            else resolution.synchronized_frame
            if resolution.synchronized_frame is not None
            else resolution.raw_frame or 0
        )
        if not self.timeline.minimum() <= timeline_frame <= self.timeline.maximum():
            self.set_timeline_range(
                min(self.timeline.minimum(), timeline_frame),
                max(self.timeline.maximum(), timeline_frame),
            )
        self.timeline.setValue(timeline_frame)
        self._select_quality_issue(resolution.issue_id)
        self._fill_browse_selectors(resolution)
        self._suppress_browse = False
        enabled = bool(resolution.can_edit and session is not None)
        for widget in (
            self.x_value,
            self.y_value,
            self.confidence_value,
            self.note_value,
            self.undo_button,
            self.redo_button,
            self.reset_button,
            self.save_button,
            self.save_rerun_button,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self._pending_skeleton_camera = None
            self.session_status.setText(f"仅查看：{resolution.blocker or '当前目标不可编辑'}")
            return
        self.session_status.setText(f"已定位问题 {resolution.issue_id}")
        target_camera = resolution.edit_target.address.camera if resolution.edit_target else None
        if self.provider is not None and target_camera is not None:
            self._pending_skeleton_camera = target_camera
        else:
            self._pending_skeleton_camera = None
            self._refresh_point_fields()

    def _fill_browse_selectors(self, resolution: CorrectionResolution) -> None:
        self.person_selector.blockSignals(True)
        self.keypoint_selector.blockSignals(True)
        self.person_selector.clear()
        self.keypoint_selector.clear()
        frame_pose_method = getattr(getattr(self.session, "document", None), "frame_pose", None)
        frame_pose = None
        if callable(frame_pose_method):
            try:
                frame_pose = frame_pose_method()
            except (OSError, ValueError, KeyError):
                frame_pose = None
        if frame_pose is not None:
            for person in frame_pose.people:
                label = person.project_person_id or f"人物 {person.raw_person_index}"
                self.person_selector.addItem(label, person.raw_person_index)
            target = resolution.edit_target
            person_index = target.person.raw_person_index if target is not None else 0
            selected_person = next(
                (person for person in frame_pose.people if person.raw_person_index == person_index),
                frame_pose.people[0] if frame_pose.people else None,
            )
            if selected_person is not None:
                for index, point in enumerate(selected_person.keypoints):
                    self.keypoint_selector.addItem(point.name, index)
        if not self.person_selector.count():
            self.person_selector.addItem("人物 0", 0)
        if not self.keypoint_selector.count():
            self.keypoint_selector.addItem("index-000", 0)
        target = resolution.edit_target
        if target is not None:
            person_index = self.person_selector.findData(target.person.raw_person_index)
            if person_index >= 0:
                self.person_selector.setCurrentIndex(person_index)
            keypoint_index = self.keypoint_selector.findData(target.keypoint.source_index)
            if keypoint_index >= 0:
                self.keypoint_selector.setCurrentIndex(keypoint_index)
        self.person_selector.blockSignals(False)
        self.keypoint_selector.blockSignals(False)

    def nudge_selected(self, x_steps: int, y_steps: int) -> None:
        target = self._editable_target()
        if target is None:
            return
        x, y, _ = self.session.document.value_at(target)
        step = max(0.1, float(self.settings.value("correction/nudge_step", 1.0)))
        self.session.apply_point(
            target,
            x + float(x_steps) * step,
            y + float(y_steps) * step,
            confidence=1.0,
        )
        self._refresh_point_fields()

    def undo_selected(self) -> None:
        if self._editable_target() is None:
            return
        self.session.undo()
        self._refresh_point_fields()

    def redo_selected(self) -> None:
        if self._editable_target() is None:
            return
        self.session.redo()
        self._refresh_point_fields()

    def reset_selected_frame(self) -> None:
        target = self._editable_target()
        if target is None:
            return
        self.session.reset_frame(target.address.frame)
        self._refresh_point_fields()

    def _editable_target(self) -> CorrectionTarget | None:
        if self.session is None or self.resolution is None or not self.resolution.can_edit:
            return None
        return self.resolution.edit_target

    def _refresh_point_fields(self) -> None:
        target = self._editable_target()
        if target is None:
            return
        x, y, confidence = self.session.document.value_at(target)
        self.x_value.setValue(round(x))
        self.y_value.setValue(round(y))
        self.confidence_value.setValue(round(confidence * 100))
        for index, card in enumerate(self._view_cards):
            if card.property("camera") == target.address.camera:
                self._refresh_skeleton_points(index, target)
                self._canvases[index].set_selected_point(x, y)

    def _present_pending_skeleton(self, camera: str) -> None:
        if self._pending_skeleton_camera != camera:
            return
        self._pending_skeleton_camera = None
        self._refresh_point_fields()

    def _clear_camera_canvas(self, camera: str) -> None:
        for index, card in enumerate(self._view_cards):
            if card.property("camera") == camera:
                self._canvases[index].clear()

    def _refresh_skeleton_points(self, view_index: int, target: CorrectionTarget) -> None:
        frame_pose_method = getattr(self.session.document, "frame_pose", None)
        if not callable(frame_pose_method):
            self._canvases[view_index].set_pose_points(
                {target.keypoint.keypoint_name: self.session.document.value_at(target)}
            )
            return
        try:
            frame_pose = frame_pose_method()
        except (OSError, ValueError, KeyError):
            return
        semantic = [
            person
            for person in frame_pose.people
            if person.project_person_id == target.person.project_person_id
        ]
        if len(semantic) == 1:
            person = semantic[0]
        else:
            raw = [
                person
                for person in frame_pose.people
                if person.raw_person_index == target.person.raw_person_index
            ]
            if len(raw) != 1:
                return
            person = raw[0]
        points = {
            point.name: (point.x, point.y, point.confidence)
            for point in person.keypoints
        }
        edges = self._topologies.edges_for(target.keypoint.model_name, points)
        self._canvases[view_index].set_pose_points(points, edges=edges)

    def _canvas_point_moved(self, view_index: int, x: float, y: float) -> None:
        target = self._editable_target()
        if target is None:
            return
        if self._view_cards[view_index].property("camera") != target.address.camera:
            return
        self.session.apply_point(target, x, y, confidence=1.0)
        self._refresh_point_fields()

    def persist_layout(self) -> None:
        self.settings.setValue("correction/workspace_sizes", self.workspace_splitter.sizes())
        self.settings.setValue("correction/view_sizes", self.views_splitter.sizes())
        if len(self._view_row_splitters) == 2:
            self.settings.setValue("correction/view_top_sizes", self._view_row_splitters[0].sizes())
            self.settings.setValue("correction/view_bottom_sizes", self._view_row_splitters[1].sizes())
        self.settings.setValue("correction/view_count", int(self.view_count.currentData()))

    def _restore_layout(self) -> None:
        view_count = self.settings.value("correction/view_count", 2, type=int)
        view_index = self.view_count.findData(view_count)
        if view_index >= 0:
            self.view_count.setCurrentIndex(view_index)
        workspace_sizes = self.settings.value("correction/workspace_sizes")
        if isinstance(workspace_sizes, list) and len(workspace_sizes) == 3:
            self.workspace_splitter.setSizes([int(value) for value in workspace_sizes])
        view_sizes = self.settings.value("correction/view_sizes")
        if isinstance(view_sizes, list) and len(view_sizes) == 2:
            self.views_splitter.setSizes([int(value) for value in view_sizes])
        elif isinstance(view_sizes, list) and len(view_sizes) == 4:
            self._view_row_splitters[0].setSizes([int(value) for value in view_sizes[:2]])
            self._view_row_splitters[1].setSizes([int(value) for value in view_sizes[2:]])
        for key, row in zip(
            ("correction/view_top_sizes", "correction/view_bottom_sizes"),
            self._view_row_splitters,
        ):
            sizes = self.settings.value(key)
            if isinstance(sizes, list) and len(sizes) == 2:
                row.setSizes([int(value) for value in sizes])

    def dirty_state(self) -> DirtyState:
        dirty = bool(self.session is not None and self.session.has_unsaved_changes())
        return DirtyState(dirty, "二维修正", "存在未保存的二维关节点修改" if dirty else "")

    def save(self) -> bool:
        if self.session is None:
            self.session_status.setText("无会话可保存")
            return False
        try:
            count, _ = self.session.save(note=self.note_value.text())
        except Exception as exc:
            self.session_status.setText(f"保存失败：{exc}")
            return False
        self.session_status.setText(f"已保存 {count} 项")
        return True

    def discard_unsaved(self) -> None:
        if self.session is not None:
            self.session.discard_unsaved()
            self.session_status.setText("已放弃未保存修改")

    def save_and_rerun(self) -> None:
        if not self.save():
            return
        if self.controller is None or not hasattr(self.controller, "request_correction_rerun"):
            self.session_status.setText("已保存；未配置选择性重跑控制器")
            return
        try:
            started = bool(self.controller.request_correction_rerun(self.session.session_id))
        except Exception as exc:
            self.session_status.setText(f"已保存；重跑启动失败：{exc}")
            return
        self.session_status.setText("已保存并启动选择性重跑" if started else "已保存；重跑未启动")

    def _previous_issue(self) -> None:
        if self.session is not None:
            self.session.previous_issue()

    def _next_issue(self) -> None:
        if self.session is not None:
            self.session.next_issue()

    def _reset_current_frame(self) -> None:
        self.reset_selected_frame()

    def _on_frame_ready(self, camera: str, frame: int, image: object) -> None:
        if self._expected_frames.get(camera) != frame:
            return
        for index, card in enumerate(self._view_cards):
            if card.property("camera") == camera:
                self._canvases[index].set_frame(image)
                self._view_labels[index].setText(self._video_status(camera, f"帧 {frame}"))
        self._present_pending_skeleton(camera)
        if (
            self._play_timer.isActive()
            and self._playback_waiting_for_video
            and camera == self.camera_selector.currentText()
        ):
            self._playback_waiting_for_video = False

    def _on_frame_failed(self, camera: str, frame: int, reason: str) -> None:
        if self._expected_frames.get(camera) != frame:
            return
        for index, card in enumerate(self._view_cards):
            if card.property("camera") == camera:
                self._view_labels[index].setText(
                    self._video_status(camera, f"帧 {frame} · {reason}")
                )
        if self._pending_skeleton_camera == camera:
            self._clear_camera_canvas(camera)
        self._present_pending_skeleton(camera)
        if (
            self._play_timer.isActive()
            and self._playback_waiting_for_video
            and camera == self.camera_selector.currentText()
        ):
            self._playback_waiting_for_video = False
