"""Resizable 2D correction workspace for dense issue-review sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
from app.application.dirty_state import DirtyState

from ..layout import make_resizable_splitter, make_scrollable_panel

if TYPE_CHECKING:
    from app.application.quality_correction_service import CorrectionResolution


class CorrectionCanvas(QWidget):
    """Image-space canvas with a draggable selected keypoint."""

    point_moved = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._selected_point: QPointF | None = None
        self._points: dict[str, tuple[float, float, float]] = {}
        self._zoom = 1.0
        self._dragging_point = False
        self.setMinimumSize(120, 100)
        self.setMouseTracking(True)

    @property
    def has_frame(self) -> bool:
        return not self._image.isNull()

    @property
    def point_count(self) -> int:
        return len(self._points)

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
        self.update()

    def set_selected_point(self, x: float, y: float) -> None:
        self._selected_point = QPointF(float(x), float(y))
        self.update()

    def set_pose_points(self, points: dict[str, tuple[float, float, float]]) -> None:
        self._points = dict(points)
        self.update()

    def clear(self) -> None:
        self._image = QImage()
        self._selected_point = None
        self._points.clear()
        self._zoom = 1.0
        self._dragging_point = False
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d141c"))
        target = self._image_rect()
        if not self._image.isNull():
            painter.drawImage(target, self._image)
        if not target.isEmpty():
            painter.setPen(QPen(QColor("#75d7c7"), 1))
            painter.setBrush(QColor(117, 215, 199, 125))
            for x, y, confidence in self._points.values():
                if confidence <= 0:
                    continue
                painter.drawEllipse(self._image_to_widget(QPointF(x, y)), 3, 3)
        if self._selected_point is not None and not target.isEmpty():
            point = self._image_to_widget(self._selected_point)
            painter.setPen(QPen(QColor("#f5c451"), 2))
            painter.setBrush(QColor(245, 196, 81, 80))
            painter.drawEllipse(point, 7, 7)
            painter.drawLine(point + QPointF(-11, 0), point + QPointF(11, 0))
            painter.drawLine(point + QPointF(0, -11), point + QPointF(0, 11))

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._selected_point is not None
            and not self._image.isNull()
        ):
            selected = self._image_to_widget(self._selected_point)
            delta = event.position() - selected
            self._dragging_point = delta.x() ** 2 + delta.y() ** 2 <= 16 ** 2
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging_point:
            point = self._widget_to_image(event.position())
            x = min(max(point.x(), 0.0), max(0.0, self._image.width() - 1.0))
            y = min(max(point.y(), 0.0), max(0.0, self._image.height() - 1.0))
            self.set_selected_point(x, y)
            self.point_moved.emit(x, y)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_point = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        self._zoom = min(8.0, max(0.25, self._zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()
        event.accept()

    def _image_rect(self) -> QRectF:
        if self._image.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRectF()
        scale = min(self.width() / self._image.width(), self.height() / self._image.height()) * self._zoom
        width = self._image.width() * scale
        height = self._image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _image_to_widget(self, point: QPointF) -> QPointF:
        target = self._image_rect()
        return QPointF(
            target.left() + point.x() * target.width() / self._image.width(),
            target.top() + point.y() * target.height() / self._image.height(),
        )

    def _widget_to_image(self, point: QPointF) -> QPointF:
        target = self._image_rect()
        return QPointF(
            (point.x() - target.left()) * self._image.width() / target.width(),
            (point.y() - target.top()) * self._image.height() / target.height(),
        )


class CorrectionPage(QWidget):
    frame_requested = Signal(int)

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
        self._expected_frames: dict[str, int] = {}
        self._camera_names: list[str] = []
        self._view_addresses: dict[str, FrameAddress] = {}
        self._view_failures: dict[str, str] = {}
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

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("correction_header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 4, 8, 4)
        title = QLabel("二维修正")
        title.setStyleSheet("font-size: 19px; font-weight: 700; color: #ffffff;")
        subtitle = QLabel("人工确认点位后再保存；同步帧与原视频帧分开显示")
        subtitle.setStyleSheet("color: #aab9c4;")
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
        title.setStyleSheet("font-weight: 700; color: #ffffff;")
        layout.addWidget(title)
        self.issue_filter = QComboBox()
        self.issue_filter.addItems(["全部问题", "待处理", "已处理", "已延期", "已忽略"])
        self.issue_filter.setObjectName("correction_issue_filter")
        layout.addWidget(self.issue_filter)
        self.issue_list = QListWidget()
        self.issue_list.setObjectName("correction_issue_list")
        self.issue_list.addItem("暂无质量问题")
        layout.addWidget(self.issue_list, 1)
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
        self.view_hint.setStyleSheet("color: #75d7c7;")
        controls.addWidget(self.view_hint)
        layout.addLayout(controls)

        self.views_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.views_splitter.setObjectName("correction_views_splitter")
        self.views_splitter.setChildrenCollapsible(False)
        self.views_splitter.setHandleWidth(5)
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
            label.setStyleSheet("color: #aab9c4; padding: 3px;")
            canvas = CorrectionCanvas()
            canvas.setObjectName(f"correction_canvas_{index + 1}")
            canvas.point_moved.connect(
                lambda x, y, view_index=index: self._canvas_point_moved(view_index, x, y)
            )
            card_layout.addWidget(label)
            card_layout.addWidget(canvas, 1)
            self.views_splitter.addWidget(card)
            self._view_cards.append(card)
            self._view_labels.append(label)
            self._canvases.append(canvas)
        layout.addWidget(self.views_splitter, 1)
        for index, card in enumerate(self._view_cards):
            card.setVisible(index < 2)
        return panel

    def _build_details_panel(self) -> QScrollArea:
        details = QWidget()
        details.setMinimumHeight(640)
        details.setObjectName("correction_details_content")
        layout = QVBoxLayout(details)
        layout.setContentsMargins(10, 6, 10, 6)
        title = QLabel("当前目标")
        title.setStyleSheet("font-weight: 700; color: #ffffff;")
        layout.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.current_camera = QLabel("—")
        self.synchronized_frame = QLabel("—")
        self.raw_frame = QLabel("—")
        self.person_value = QLabel("—")
        self.keypoint_value = QLabel("—")
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
        self.timeline.sliderReleased.connect(
            lambda: self.frame_requested.emit(self.timeline.value())
        )
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
        for index, card in enumerate(self._view_cards):
            card.setVisible(index < count)
        self.settings.setValue("correction/view_count", count)
        if self._view_addresses or self._view_failures:
            self._request_visible_frames()

    def set_timeline_range(self, first_frame: int, last_frame: int) -> None:
        first = max(0, int(first_frame))
        last = max(first, int(last_frame))
        self.timeline.setRange(first, last)

    def _request_relative_frame(self, offset: int) -> None:
        requested = min(
            self.timeline.maximum(),
            max(self.timeline.minimum(), self.timeline.value() + int(offset)),
        )
        self.frame_requested.emit(requested)

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

    def _select_camera(self, camera: str, *, persist: bool = True) -> None:
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
        if self._view_addresses or self._view_failures:
            self._request_visible_frames()

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
                self._view_labels[index].setText(f"{camera} · 正在读取原视频帧 {address.frame}")
                self.provider.request(address)

    def clear_project_context(self) -> None:
        self.session = None
        self.resolution = None
        self._expected_frames.clear()
        self._view_addresses.clear()
        self._view_failures.clear()
        self.current_camera.setText("—")
        self.synchronized_frame.setText("—")
        self.raw_frame.setText("—")
        self.person_value.setText("—")
        self.keypoint_value.setText("—")
        self.x_value.setValue(0)
        self.y_value.setValue(0)
        self.confidence_value.setValue(0)
        self.issue_list.clear()
        self.issue_list.addItem("暂无质量问题")
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

    def open_resolution(
        self,
        resolution: CorrectionResolution,
        session: Any,
    ) -> None:
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
        synchronized_frame = resolution.synchronized_frame or 0
        if not self.timeline.minimum() <= synchronized_frame <= self.timeline.maximum():
            self.set_timeline_range(
                min(self.timeline.minimum(), synchronized_frame),
                max(self.timeline.maximum(), synchronized_frame),
            )
        self.timeline.setValue(synchronized_frame)
        self.issue_list.clear()
        self.issue_list.addItem(resolution.issue_id)
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
            self.session_status.setText(f"仅查看：{resolution.blocker or '当前目标不可编辑'}")
            return
        self.session_status.setText(f"已定位问题 {resolution.issue_id}")
        self._refresh_point_fields()

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
        self._canvases[view_index].set_pose_points(
            {
                point.name: (point.x, point.y, point.confidence)
                for point in person.keypoints
            }
        )

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
        if isinstance(view_sizes, list) and len(view_sizes) == 4:
            self.views_splitter.setSizes([int(value) for value in view_sizes])

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
                self._view_labels[index].setText(f"{camera} · 原视频帧 {frame}")

    def _on_frame_failed(self, camera: str, frame: int, reason: str) -> None:
        if self._expected_frames.get(camera) != frame:
            return
        for index, card in enumerate(self._view_cards):
            if card.property("camera") == camera:
                self._view_labels[index].setText(f"{camera} · 原视频帧 {frame} · {reason}")
