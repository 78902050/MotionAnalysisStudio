"""Resizable 2D correction workspace for dense issue-review sessions."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
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

from app.domain.addresses import CorrectionTarget, FrameAddress

from ..layout import make_resizable_splitter, make_scrollable_panel


class CorrectionPage(QWidget):
    def __init__(self, provider: Any = None, session: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.provider = provider
        self.session = session
        self._view_cards: list[QFrame] = []
        self._build_ui()
        if self.provider is not None:
            self.provider.frame_ready.connect(self._on_frame_ready)
            self.provider.frame_failed.connect(self._on_frame_failed)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)
        root_layout.addWidget(self._build_header())

        workspace = make_resizable_splitter(
            self._build_issue_panel(),
            self._build_view_panel(),
            self._build_details_panel(),
        )
        workspace.setObjectName("correction_workspace_splitter")
        workspace.setSizes([220, 560, 280])
        root_layout.addWidget(workspace, 1)
        root_layout.addWidget(self._build_action_bar())
        self._install_shortcuts()

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

    def _build_issue_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("correction_issue_panel")
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
        return panel

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
        self.camera_selector.addItems(["cam01", "cam02", "cam03", "cam04"])
        self.camera_selector.setObjectName("correction_camera_selector")
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
            card.setMinimumWidth(120)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card_layout = QVBoxLayout(card)
            label = QLabel(f"cam0{index + 1}\n等待原视频帧")
            label.setObjectName(f"correction_view_label_{index + 1}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setStyleSheet("background: #0d141c; color: #aab9c4; padding: 18px;")
            card_layout.addWidget(label, 1)
            self.views_splitter.addWidget(card)
            self._view_cards.append(card)
        layout.addWidget(self.views_splitter, 1)
        self.set_view_count(2)
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

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("correction_action_bar")
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
        self.undo_button.clicked.connect(lambda: self.session and self.session.undo())
        self.redo_button.clicked.connect(lambda: self.session and self.session.redo())
        self.reset_button.clicked.connect(self._reset_current_frame)
        self.save_button.clicked.connect(self.save)
        self.save_rerun_button.clicked.connect(self.save_and_rerun)
        return bar

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_button.click)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)

    def set_view_count(self, count: int) -> None:
        count = int(count)
        if count not in {1, 2, 4}:
            raise ValueError("view count must be 1, 2 or 4")
        for index, card in enumerate(self._view_cards):
            card.setVisible(index < count)

    def set_target(self, target: CorrectionTarget) -> None:
        self.current_camera.setText(target.address.camera)
        self.synchronized_frame.setText(str(target.address.frame))
        self.raw_frame.setText("等待映射")
        self.person_value.setText(target.person.project_person_id)
        self.keypoint_value.setText(target.keypoint.keypoint_name)
        if self.provider is not None and target.address.timeline == "raw":
            self.provider.request(target.address)

    def save(self) -> None:
        if self.session is None:
            self.session_status.setText("无会话可保存")
            return
        count, _ = self.session.save(note=self.note_value.text())
        self.session_status.setText(f"已保存 {count} 项")

    def save_and_rerun(self) -> None:
        self.save()
        self.session_status.setText("已保存；选择性重跑由任务中心启动")

    def _previous_issue(self) -> None:
        if self.session is not None:
            self.session.previous_issue()

    def _next_issue(self) -> None:
        if self.session is not None:
            self.session.next_issue()

    def _reset_current_frame(self) -> None:
        if self.session is not None:
            self.session.reset_frame(self.timeline.value())

    def _on_frame_ready(self, camera: str, frame: int, _image: object) -> None:
        for card in self._view_cards:
            label = card.findChild(QLabel)
            if label is not None and label.text().startswith(camera):
                label.setText(f"{camera}\n原视频帧 {frame}\n已加载")

    def _on_frame_failed(self, camera: str, frame: int, reason: str) -> None:
        for card in self._view_cards:
            label = card.findChild(QLabel)
            if label is not None and label.text().startswith(camera):
                label.setText(f"{camera}\n原视频帧 {frame}\n{reason}")
