"""Resizable, non-blocking 3D skeletal trajectory playback page."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.application.controller import ApplicationController
from app.gui.widgets.trajectory_canvas import TrajectoryCanvas
from app.playback.catalog import TrajectoryCatalog
from app.playback.clock import PlaybackClock
from app.playback.model import PlaybackTrajectory, TrajectorySource
from app.playback.readers import load_playback_trajectory
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskRequest
from app.tasks.handle import TaskHandle
from app.visualization.skeleton import SkeletonTopologyRepository

from ..layout import make_resizable_splitter, make_scrollable_panel


class Playback3DPage(QWidget):
    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
        *,
        controller: ApplicationController | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.controller = controller
        self.settings = settings or QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
        self.trajectory: PlaybackTrajectory | None = None
        self.frame_index = 0
        self.pending_target: tuple[str, int] | None = None
        self._handle: TaskHandle | None = None
        self._clock = PlaybackClock()
        self._topologies = SkeletonTopologyRepository()
        self.load_timer = QTimer(self)
        self.load_timer.setInterval(25)
        self.load_timer.timeout.connect(self._poll_load)
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._tick)
        self._build_ui()
        self._restore_layout()
        if project is not None:
            self.set_project(project)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        header = QFrame()
        header.setObjectName("playback_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        title = QLabel("三维骨骼回放")
        title.setProperty("uiRole", "pageTitle")
        header_layout.addWidget(title)
        self.source_selector = QComboBox()
        self.source_selector.setObjectName("playback_source_selector")
        self.source_selector.setMinimumWidth(240)
        self.source_selector.currentIndexChanged.connect(self._source_changed)
        header_layout.addWidget(self.source_selector, 1)
        self.reload_button = QPushButton("重新读取")
        self.reload_button.clicked.connect(self._load_selected)
        header_layout.addWidget(self.reload_button)
        self.status = QLabel("请先打开含 TRC/C3D 的项目")
        self.status.setObjectName("playback_status")
        self.status.setWordWrap(True)
        header_layout.addWidget(self.status, 1)
        root.addWidget(header)

        self.canvas = TrajectoryCanvas()
        self.canvas.setObjectName("trajectory_canvas")
        inspector = QWidget()
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(10, 10, 10, 10)
        form = QFormLayout()
        self.person_value = QLabel("—")
        self.variant_value = QLabel("—")
        self.format_value = QLabel("—")
        self.frame_value = QLabel("—")
        self.time_value = QLabel("—")
        self.marker_value = QLabel("—")
        self.unit_value = QLabel("—")
        self.selected_value = QLabel("—")
        self.canvas.point_selected.connect(self.selected_value.setText)
        form.addRow("人物", self.person_value)
        form.addRow("版本", self.variant_value)
        form.addRow("格式", self.format_value)
        form.addRow("当前帧", self.frame_value)
        form.addRow("时间", self.time_value)
        form.addRow("标记点", self.marker_value)
        form.addRow("单位", self.unit_value)
        form.addRow("选中点", self.selected_value)
        inspector_layout.addLayout(form)
        self.diagnostics = QLabel("尚未读取轨迹")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setObjectName("playback_diagnostics")
        inspector_layout.addWidget(self.diagnostics)
        inspector_layout.addStretch(1)
        inspector_scroll = make_scrollable_panel(inspector)
        inspector_scroll.setObjectName("playback_inspector_scroll")
        self.workspace_splitter = make_resizable_splitter(self.canvas, inspector_scroll)
        self.workspace_splitter.setObjectName("playback_workspace_splitter")
        self.workspace_splitter.setSizes([760, 260])
        self.workspace_splitter.splitterMoved.connect(lambda *_: self._persist_layout())
        root.addWidget(self.workspace_splitter, 1)

        timeline_row = QHBoxLayout()
        self.previous_button = QPushButton("上一帧")
        self.previous_button.clicked.connect(lambda: self._step(-1))
        timeline_row.addWidget(self.previous_button)
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("playback_play_button")
        self.play_button.clicked.connect(self.play)
        timeline_row.addWidget(self.play_button)
        self.next_button = QPushButton("下一帧")
        self.next_button.clicked.connect(lambda: self._step(1))
        timeline_row.addWidget(self.next_button)
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.valueChanged.connect(self._timeline_changed)
        timeline_row.addWidget(self.timeline, 1)
        self.speed_selector = QComboBox()
        for value in (0.25, 0.5, 1.0, 1.5, 2.0):
            self.speed_selector.addItem(f"{value:g}×", value)
        self.speed_selector.setCurrentIndex(2)
        self.speed_selector.currentIndexChanged.connect(self._speed_changed)
        timeline_row.addWidget(self.speed_selector)
        self.loop_checkbox = QCheckBox("循环")
        timeline_row.addWidget(self.loop_checkbox)
        root.addLayout(timeline_row)

        view_row = QHBoxLayout()
        for label, yaw, pitch in (
            ("正视", 0.0, 0.0),
            ("侧视", math.pi / 2, 0.0),
            ("俯视", 0.0, math.pi / 2),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, y=yaw, p=pitch: self.canvas.set_view(y, p)
            )
            view_row.addWidget(button)
        direction_pad = QFrame()
        direction_pad.setObjectName("playback_direction_pad")
        direction_layout = QGridLayout(direction_pad)
        direction_layout.setContentsMargins(4, 2, 4, 2)
        direction_layout.setHorizontalSpacing(3)
        direction_layout.setVerticalSpacing(3)
        angle = math.pi / 12
        for label, object_name, row, column, yaw_delta, pitch_delta, tooltip in (
            ("↑", "playback_rotate_up", 0, 1, 0.0, angle, "视角向上旋转 15°"),
            ("←", "playback_rotate_left", 1, 0, -angle, 0.0, "视角向左旋转 15°"),
            ("·", "playback_rotate_reset", 1, 1, 0.0, 0.0, "恢复默认观察角度"),
            ("→", "playback_rotate_right", 1, 2, angle, 0.0, "视角向右旋转 15°"),
            ("↓", "playback_rotate_down", 2, 1, 0.0, -angle, "视角向下旋转 15°"),
        ):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setToolTip(tooltip)
            button.setFixedSize(32, 26)
            if object_name == "playback_rotate_reset":
                button.clicked.connect(lambda: self.canvas.set_view(-0.35, -0.20))
            else:
                button.clicked.connect(
                    lambda _checked=False, y=yaw_delta, p=pitch_delta: self.canvas.rotate_by(y, p)
                )
            direction_layout.addWidget(button, row, column)
        view_row.addWidget(direction_pad)
        fit_button = QPushButton("适应当前")
        fit_button.clicked.connect(self.canvas.fit_all)
        view_row.addWidget(fit_button)
        fit_ghosts_button = QPushButton("适应残影")
        fit_ghosts_button.setObjectName("playback_fit_ghosts")
        fit_ghosts_button.clicked.connect(self.canvas.fit_motion_window)
        view_row.addWidget(fit_ghosts_button)
        self.ghost_checkbox = QCheckBox("骨架残影")
        self.ghost_checkbox.setObjectName("playback_ghost_poses")
        self.ghost_checkbox.setChecked(True)
        self.ghost_checkbox.toggled.connect(self.canvas.set_ghost_poses_enabled)
        view_row.addWidget(self.ghost_checkbox)
        view_row.addWidget(QLabel("残影范围"))
        self.trail_spin = QSpinBox()
        self.trail_spin.setRange(0, 120)
        self.trail_spin.setValue(45)
        self.trail_spin.setSuffix(" 帧")
        self.trail_spin.valueChanged.connect(self.canvas.set_trail_frames)
        view_row.addWidget(self.trail_spin)
        view_row.addStretch(1)
        root.addLayout(view_row)

    def set_project(self, project: ProjectManager | None) -> None:
        self.stop()
        self.project = project
        self.trajectory = None
        self.pending_target = None
        self.canvas.set_trajectory(None)
        self.source_selector.blockSignals(True)
        self.source_selector.clear()
        sources = TrajectoryCatalog.scan(project.root) if project is not None else ()
        for source in sources:
            self.source_selector.addItem(source.display_name, source)
        self.source_selector.blockSignals(False)
        if project is None:
            self.status.setText("请先打开含 TRC/C3D 的项目")
        elif not sources:
            self.status.setText(f"未在 {project.root / 'pose-3d'} 发现可回放的 TRC/C3D")
        else:
            self.status.setText(f"发现 {len(sources)} 条三维轨迹，正在后台读取…")
            self._load_selected()

    def _source_changed(self) -> None:
        self.stop()
        self.trajectory = None
        self.canvas.set_trajectory(None)
        self._load_selected()

    def _load_selected(self) -> None:
        source = self.source_selector.currentData()
        if not isinstance(source, TrajectorySource):
            return
        if self._handle is not None:
            self._handle.cancel()
        self.status.setText(f"正在后台读取 {source.path.name}…")
        if (
            self.controller is not None
            and self.project is not None
            and self.controller.current_project is self.project
        ):
            project_id = str(self.project.manifest["project_id"])
            request = TaskRequest(project_id, self.controller.generation, "trajectory-playback-load", {})
            self._handle = self.controller.start_task(
                request, lambda token: self._load_work(source, token)
            )
            self.load_timer.start()
            return
        try:
            self._finish_load(self._load_work(source, CancellationToken()))
        except Exception as exc:
            self.status.setText(f"轨迹读取失败：{type(exc).__name__}: {exc}")

    @staticmethod
    def _load_work(source: TrajectorySource, token: CancellationToken) -> PlaybackTrajectory:
        token.raise_if_cancelled()
        trajectory = load_playback_trajectory(source)
        token.raise_if_cancelled()
        return trajectory

    def _poll_load(self) -> None:
        handle = self._handle
        if handle is None:
            self.load_timer.stop()
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self.load_timer.stop()
        self._handle = None
        if self.project is None or self.controller is None:
            return
        if not self.controller.supervisor.accepts_result(
            result,
            str(self.project.manifest["project_id"]),
            self.controller.generation,
        ):
            return
        if result.status != "succeeded" or not isinstance(result.value, PlaybackTrajectory):
            self.status.setText(f"轨迹读取失败：{result.error or result.status}")
            return
        self._finish_load(result.value)

    def _finish_load(self, trajectory: PlaybackTrajectory) -> None:
        self.trajectory = trajectory
        self.frame_index = 0
        edges = self._topologies.edges_for_labels(trajectory.labels)
        self.canvas.set_trajectory(trajectory, edges)
        self.timeline.setRange(0, len(trajectory.frames) - 1)
        self.timeline.setValue(0)
        source = trajectory.source
        self.person_value.setText(source.person_id)
        self.variant_value.setText(source.variant)
        self.format_value.setText(source.format.upper())
        self.marker_value.setText(str(len(trajectory.points)))
        self.unit_value.setText(trajectory.coordinate_unit)
        self.diagnostics.setText(
            "\n".join(item.message for item in trajectory.diagnostics) or "轨迹结构完整"
        )
        self.status.setText(
            f"已读取 {len(trajectory.frames)} 帧、{len(trajectory.points)} 个标记点、{len(edges)} 条骨架边"
        )
        self._update_frame_details()
        self._apply_pending_target()

    def play(self) -> None:
        if self.trajectory is None:
            self.status.setText("请先选择并读取一条轨迹")
            return
        if self.play_timer.isActive():
            self._pause()
            return
        if self.frame_index >= len(self.trajectory.frames) - 1:
            self.set_frame_index(0)
        self._clock.start(
            time.monotonic(),
            self.trajectory.times[self.frame_index],
            float(self.speed_selector.currentData()),
        )
        self.play_timer.start()
        self.play_button.setText("暂停")

    def _pause(self) -> None:
        if self._clock.running:
            self._clock.pause(time.monotonic())
        self.play_timer.stop()
        self.play_button.setText("播放")

    def _tick(self) -> None:
        trajectory = self.trajectory
        if trajectory is None:
            self._pause()
            return
        now = time.monotonic()
        source_time = self._clock.time_at(now)
        if source_time > trajectory.times[-1]:
            if self.loop_checkbox.isChecked():
                self.set_frame_index(0)
                self._clock.start(
                    now, trajectory.times[0], float(self.speed_selector.currentData())
                )
            else:
                self.set_frame_index(len(trajectory.frames) - 1)
                self._pause()
            return
        self.set_frame_index(self._clock.frame_index(trajectory.times, now))

    def _speed_changed(self) -> None:
        if self.trajectory is None or not self.play_timer.isActive():
            return
        now = time.monotonic()
        self._clock.start(
            now,
            self._clock.time_at(now),
            float(self.speed_selector.currentData()),
        )

    def _step(self, offset: int) -> None:
        self._pause()
        self.set_frame_index(self.frame_index + int(offset))

    def set_frame_index(self, index: int) -> None:
        if self.trajectory is None:
            return
        index = min(len(self.trajectory.frames) - 1, max(0, int(index)))
        self.frame_index = index
        self.timeline.blockSignals(True)
        self.timeline.setValue(index)
        self.timeline.blockSignals(False)
        self.canvas.set_frame_index(index)
        self._update_frame_details()

    def _timeline_changed(self, value: int) -> None:
        if self.trajectory is None:
            return
        self._pause()
        self.frame_index = int(value)
        self.canvas.set_frame_index(self.frame_index)
        self._update_frame_details()

    def _update_frame_details(self) -> None:
        if self.trajectory is None:
            self.frame_value.setText("—")
            self.time_value.setText("—")
            return
        self.frame_value.setText(str(self.trajectory.frames[self.frame_index]))
        self.time_value.setText(f"{self.trajectory.times[self.frame_index]:.3f} s")

    def open_target(self, person_id: str, frame: int) -> None:
        self.pending_target = (str(person_id), int(frame))
        matches = [
            index
            for index in range(self.source_selector.count())
            if isinstance(self.source_selector.itemData(index), TrajectorySource)
            and self.source_selector.itemData(index).person_id == person_id
        ]
        if len(matches) == 1:
            if self.source_selector.currentIndex() != matches[0]:
                self.source_selector.setCurrentIndex(matches[0])
            else:
                self._apply_pending_target()
        elif not matches:
            self.status.setText(f"未找到人物 {person_id} 的三维轨迹，请手动选择来源")
        else:
            self.status.setText(f"人物 {person_id} 有多条三维轨迹，请先选择版本")

    def _apply_pending_target(self) -> None:
        if self.pending_target is None or self.trajectory is None:
            return
        person_id, frame = self.pending_target
        if self.trajectory.source.person_id != person_id:
            return
        index = min(
            range(len(self.trajectory.frames)),
            key=lambda candidate: abs(self.trajectory.frames[candidate] - frame),
        )
        self.set_frame_index(index)
        self.pending_target = None

    def stop(self) -> None:
        self._pause()
        self.load_timer.stop()
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _persist_layout(self) -> None:
        self.settings.setValue("playback3d/splitter_sizes", self.workspace_splitter.sizes())
        self.settings.setValue("playback3d/trail_frames", self.trail_spin.value())
        self.settings.setValue("playback3d/ghost_poses", self.ghost_checkbox.isChecked())

    def _restore_layout(self) -> None:
        sizes = self.settings.value("playback3d/splitter_sizes")
        if isinstance(sizes, list) and len(sizes) == 2:
            self.workspace_splitter.setSizes([int(value) for value in sizes])
        trail = self.settings.value("playback3d/trail_frames", 45, type=int)
        self.trail_spin.setValue(min(120, max(0, trail)))
        ghosts = self.settings.value("playback3d/ghost_poses", True, type=bool)
        self.ghost_checkbox.setChecked(bool(ghosts))

    def closeEvent(self, event) -> None:
        self._persist_layout()
        self.stop()
        event.accept()
