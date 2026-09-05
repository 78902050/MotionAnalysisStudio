"""Scrollable event and cycle workbench backed by the analysis data contracts."""

from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analysis.cycles import Cycle, CycleBuilder
from app.analysis.event_history import EventHistory
from app.analysis.events import Event, EventDetector, EventRule, time_for_frame
from app.analysis.model import MetricTable
from app.project.manager import ProjectManager

from ..layout import make_scrollable_panel


class _EventWorker(QObject):
    finished = Signal(str, int, object, object)
    failed = Signal(str, int, str)

    def __init__(self, project_id: str, generation: int, metrics: MetricTable, rule: EventRule) -> None:
        super().__init__()
        self.project_id = project_id
        self.generation = generation
        self.metrics = metrics
        self.rule = rule

    @Slot()
    def run(self) -> None:
        try:
            if QThread.currentThread().isInterruptionRequested():
                raise RuntimeError("事件检测已取消")
            events = EventDetector().detect(self.metrics, self.rule)
            cycles = CycleBuilder().build(events)
            if QThread.currentThread().isInterruptionRequested():
                raise RuntimeError("事件检测已取消")
        except Exception as exc:
            self.failed.emit(self.project_id, self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(self.project_id, self.generation, events, cycles)


class EventsPage(QWidget):
    def __init__(self, project: ProjectManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.metric_table: MetricTable | None = None
        self._events: tuple[Event, ...] = ()
        self._cycles: tuple[Cycle, ...] = ()
        self._project_id = ""
        self._generation = 0
        self._thread: QThread | None = None
        self._worker: _EventWorker | None = None
        self._history_path: Path | None = None
        self._build_ui()
        if project is not None:
            self.set_project(project)

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        heading = QLabel("事件与周期")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel(
            "按指标列和阈值检测动作事件，并在同一连续数据段内构建周期。缺失数据不会被插值成事件；人工调整追加到事件历史。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("指标列"))
        self.metric_selector = QComboBox()
        self.metric_selector.setObjectName("events_metric_selector")
        self.metric_selector.currentTextChanged.connect(self._metric_changed)
        controls.addWidget(self.metric_selector, 2)
        controls.addWidget(QLabel("单位"))
        self.metric_unit = QLabel("—")
        self.metric_unit.setObjectName("events_metric_unit")
        controls.addWidget(self.metric_unit)
        controls.addWidget(QLabel("条件"))
        self.operator_selector = QComboBox()
        self.operator_selector.addItem("上穿", "crosses_above")
        self.operator_selector.addItem("下穿", "crosses_below")
        self.operator_selector.addItem("进入阈值上方", "above")
        self.operator_selector.addItem("进入阈值下方", "below")
        self.operator_selector.setObjectName("events_operator_selector")
        controls.addWidget(self.operator_selector)
        controls.addWidget(QLabel("阈值"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.threshold.setDecimals(6)
        self.threshold.setObjectName("events_threshold")
        controls.addWidget(self.threshold)
        controls.addWidget(QLabel("事件角色"))
        self.role_selector = QComboBox()
        self.role_selector.addItem("点事件", "point")
        self.role_selector.addItem("周期开始", "start")
        self.role_selector.addItem("周期结束", "end")
        self.role_selector.setObjectName("events_role_selector")
        controls.addWidget(self.role_selector)
        self.detect_button = QPushButton("后台检测")
        self.detect_button.setObjectName("events_detect_button")
        self.detect_button.clicked.connect(self.detect)
        controls.addWidget(self.detect_button)
        layout.addLayout(controls)

        self.events_table = QTableWidget(0, 8)
        self.events_table.setObjectName("events_table")
        self.events_table.setHorizontalHeaderLabels(["事件 ID", "规则", "角色", "帧", "时间", "值", "数据段", "来源"])
        self.events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.events_table.itemSelectionChanged.connect(self._event_selected)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("检测事件"))
        layout.addWidget(self.events_table, 1)

        manual_form = QFormLayout()
        self.manual_frame = QSpinBox()
        self.manual_frame.setRange(0, 0)
        self.manual_frame.setObjectName("events_manual_frame")
        self.manual_note = QLineEdit()
        self.manual_note.setPlaceholderText("说明人工调整原因")
        self.manual_note.setObjectName("events_manual_note")
        self.manual_save_button = QPushButton("保存选中事件调整")
        self.manual_save_button.setObjectName("events_manual_save_button")
        self.manual_save_button.clicked.connect(self.save_manual_event)
        manual_form.addRow("人工事件帧", self.manual_frame)
        manual_form.addRow("备注", self.manual_note)
        manual_form.addRow("历史", self.manual_save_button)
        layout.addLayout(manual_form)

        self.cycle_table = QTableWidget(0, 6)
        self.cycle_table.setObjectName("events_cycle_table")
        self.cycle_table.setHorizontalHeaderLabels(["周期 ID", "规则", "开始帧", "结束帧", "时长", "事件来源"])
        self.cycle_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cycle_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("周期"))
        layout.addWidget(self.cycle_table, 1)

        self.status = QLabel("请先计算运动学指标")
        self.status.setObjectName("events_status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("events_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_project(self, project: ProjectManager | None) -> None:
        self._stop_worker()
        self._generation += 1
        self.project = project
        self._project_id = str(project.manifest.get("project_id", "")) if project else ""
        self._history_path = project.root / "analysis" / "events.jsonl" if project else None
        self.metric_table = None
        self._events = ()
        self._cycles = ()
        self.metric_selector.clear()
        self.metric_unit.setText("—")
        self.events_table.setRowCount(0)
        self.cycle_table.setRowCount(0)
        self.status.setText("已打开项目；请先在运动学页计算并传入指标" if project else "请先打开项目")

    def set_metric_table(self, table: MetricTable | None) -> None:
        self._stop_worker()
        self._generation += 1
        self.metric_table = table
        self._events = ()
        self._cycles = ()
        self.events_table.setRowCount(0)
        self.cycle_table.setRowCount(0)
        self.metric_selector.clear()
        if table is None:
            self.metric_unit.setText("—")
            self.status.setText("请先计算运动学指标")
            return
        self.metric_selector.addItems(list(table.columns))
        self._metric_changed(self.metric_selector.currentText())
        self._update_frame_range()
        self.status.setText(f"指标已就绪：{len(table.columns)} 列，{len(table.frames)} 帧")

    def detect(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("事件检测正在进行")
            return
        if self.metric_table is None or not self.metric_selector.currentText():
            self.status.setText("请先计算运动学指标")
            return
        self._generation += 1
        generation = self._generation
        rule_id = "rule-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", self.metric_selector.currentText()).strip("-")
        rule = EventRule(
            rule_id or "rule-metric",
            self.metric_selector.currentText(),
            self.operator_selector.currentData(),
            self.threshold.value(),
            self.metric_selector.currentText(),
            self.role_selector.currentData(),
        )
        self.detect_button.setEnabled(False)
        self.status.setText("正在后台检测事件和构建周期…")
        self._thread = QThread(self)
        self._worker = _EventWorker(self._project_id or "memory", generation, self.metric_table, rule)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._detection_finished)
        self._worker.failed.connect(self._detection_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(str, int, object, object)
    def _detection_finished(self, project_id: str, generation: int, events: object, cycles: object) -> None:
        if project_id != (self._project_id or "memory") or generation != self._generation:
            return
        if not isinstance(events, tuple) or not all(isinstance(event, Event) for event in events):
            self.status.setText("事件检测返回了无效结果")
            return
        if not isinstance(cycles, tuple) or not all(isinstance(cycle, Cycle) for cycle in cycles):
            self.status.setText("周期构建返回了无效结果")
            return
        self._events = self._load_effective_events(events)
        self._cycles = CycleBuilder().build(self._events)
        self._fill_event_table()
        self._fill_cycle_table()
        self.status.setText(f"检测完成：{len(self._events)} 个事件，{len(self._cycles)} 个周期")

    @Slot(str, int, str)
    def _detection_failed(self, project_id: str, generation: int, reason: str) -> None:
        if project_id == (self._project_id or "memory") and generation == self._generation:
            self.status.setText(f"事件检测失败：{reason}")

    def _load_effective_events(self, events: tuple[Event, ...]) -> tuple[Event, ...]:
        if self._history_path is None or not self._history_path.exists():
            return events
        try:
            return EventHistory(self._history_path).effective_events(events)
        except ValueError as exc:
            self.status.setText(f"事件历史损坏，未应用人工调整：{exc}")
            return events

    def _fill_event_table(self) -> None:
        self.events_table.setRowCount(0)
        for event in self._events:
            row = self.events_table.rowCount()
            self.events_table.insertRow(row)
            values = (
                event.event_id,
                event.rule_id,
                event.role,
                str(event.frame),
                f"{event.time:.6g}",
                f"{event.value:.6g}",
                event.segment_id,
                event.source,
            )
            for column, value in enumerate(values):
                self.events_table.setItem(row, column, QTableWidgetItem(value))

    def _fill_cycle_table(self) -> None:
        self.cycle_table.setRowCount(0)
        event_by_id = {event.event_id: event for event in self._events}
        for cycle in self._cycles:
            row = self.cycle_table.rowCount()
            self.cycle_table.insertRow(row)
            start = event_by_id.get(cycle.start_event_id)
            end = event_by_id.get(cycle.end_event_id)
            source = "/".join(sorted({event.source for event in (start, end) if event is not None}))
            values = (
                cycle.cycle_id,
                cycle.rule_id,
                str(cycle.start_frame),
                str(cycle.end_frame),
                f"{cycle.duration:.6g}",
                source,
            )
            for column, value in enumerate(values):
                self.cycle_table.setItem(row, column, QTableWidgetItem(value))

    def _event_selected(self) -> None:
        row = self.events_table.currentRow()
        if 0 <= row < len(self._events):
            self.manual_frame.setValue(self._events[row].frame)
            self.manual_note.setText(self._events[row].note)

    def save_manual_event(self) -> None:
        row = self.events_table.currentRow()
        if self.metric_table is None or not (0 <= row < len(self._events)):
            self.status.setText("请先选择一个事件")
            return
        original = self._events[row]
        frame = self.manual_frame.value()
        try:
            time = time_for_frame(self.metric_table, frame)
            index = self.metric_table.frames.index(frame)
            value = self.metric_table.column(self.metric_selector.currentText())[index]
        except (KeyError, ValueError, IndexError) as exc:
            self.status.setText(f"人工事件帧无效：{exc}")
            return
        if not math.isfinite(value):
            self.status.setText("人工事件帧缺少指标值，不能保存")
            return
        manual = Event(
            original.event_id,
            original.rule_id,
            original.role,
            frame,
            time,
            value,
            original.segment_id,
            "manual",
            self.manual_note.text().strip(),
        )
        if self._history_path is None:
            self.status.setText("内存指标没有项目历史路径，人工调整未保存")
            return
        EventHistory(self._history_path).append_manual(manual)
        self._events = self._load_effective_events(self._events)
        self._cycles = CycleBuilder().build(self._events)
        self._fill_event_table()
        self._fill_cycle_table()
        self.status.setText(f"已追加人工调整：{manual.event_id}，帧 {manual.frame}")

    def _metric_changed(self, name: str) -> None:
        self.metric_unit.setText(
            self.metric_table.units.get(name, "—") if self.metric_table is not None else "—"
        )
        self._update_frame_range()

    def _update_frame_range(self) -> None:
        if self.metric_table is None or not self.metric_table.frames:
            self.manual_frame.setRange(0, 0)
            return
        self.manual_frame.setRange(min(self.metric_table.frames), max(self.metric_table.frames))

    def _thread_finished(self) -> None:
        self.detect_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _stop_worker(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._generation += 1
        self._thread.requestInterruption()
        self._thread.quit()
        self._thread.wait(5000)

    def closeEvent(self, event) -> None:
        self._generation += 1
        self._stop_worker()
        event.accept()
