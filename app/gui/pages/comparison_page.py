"""Background comparison report page with explicit member selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analysis.comparison import ComparisonMember, ComparisonReport, ComparisonRequest, ComparisonService
from app.application.controller import ApplicationController
from app.reporting.export import ReportExporter
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest
from app.tasks.handle import TaskHandle

from ..layout import make_scrollable_panel


class _ComparisonWorker(QObject):
    finished = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(self, context_id: str, generation: int, service: ComparisonService, request: ComparisonRequest) -> None:
        super().__init__()
        self.context_id = context_id
        self.generation = generation
        self.service = service
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            if QThread.currentThread().isInterruptionRequested():
                raise RuntimeError("对比报告已取消")
            report = self.service.build(self.request)
            if QThread.currentThread().isInterruptionRequested():
                raise RuntimeError("对比报告已取消")
        except Exception as exc:
            self.failed.emit(self.context_id, self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(self.context_id, self.generation, report)


class ComparisonPage(QWidget):
    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
        *,
        controller: ApplicationController | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.controller = controller
        self._members: tuple[ComparisonMember, ...] = ()
        self._service: ComparisonService | None = None
        self.report: ComparisonReport | None = None
        self._context_id = ""
        self._generation = 0
        self._thread: QThread | None = None
        self._worker: _ComparisonWorker | None = None
        self._pending_rows = ()
        self._fill_position = 0
        self._fill_timer = QTimer(self)
        self._fill_timer.setInterval(0)
        self._fill_timer.timeout.connect(self._append_table_chunk)
        self._export_handle: TaskHandle | None = None
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(25)
        self._export_timer.timeout.connect(self._poll_export)
        self._build_ui()
        if project is not None:
            self.set_project(project)

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        heading = QLabel("对比报告")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel(
            "明确选择项目、人物和试次，再选择对齐依据。报告保留输入版本和缺失原因；缺失值不会被静默填成 0。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        members = QHBoxLayout()
        self.project_selector = self._member_list("comparison_project_selector")
        self.person_selector = self._member_list("comparison_person_selector")
        self.trial_selector = self._member_list("comparison_trial_selector")
        for title, widget in (("项目", self.project_selector), ("人物", self.person_selector), ("试次", self.trial_selector)):
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            column.addWidget(widget)
            members.addLayout(column, 1)
        layout.addLayout(members)

        controls = QHBoxLayout()
        form = QFormLayout()
        self.alignment_selector = QComboBox()
        self.alignment_selector.addItem("按帧号", "frame")
        self.alignment_selector.addItem("按时间（精确）", "time")
        self.alignment_selector.addItem("按事件出现序号", "event")
        self.alignment_selector.setObjectName("comparison_alignment_selector")
        form.addRow("对齐方式", self.alignment_selector)
        controls.addLayout(form)
        self.build_button = QPushButton("后台生成报告")
        self.build_button.setObjectName("comparison_build_button")
        self.build_button.clicked.connect(self.build_report)
        controls.addWidget(self.build_button)
        controls.addStretch(1)
        for format_name, label in (("json", "导出 JSON"), ("csv", "导出 CSV"), ("html", "导出 HTML")):
            button = QPushButton(label)
            button.setObjectName(f"comparison_export_{format_name}_button")
            button.clicked.connect(lambda _checked=False, name=format_name: self._choose_export(name))
            button.setEnabled(False)
            setattr(self, f"export_{format_name}_button", button)
            controls.addWidget(button)
        layout.addLayout(controls)

        self.summary = QLabel("尚未生成报告")
        self.summary.setObjectName("comparison_summary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.comparison_table = QTableWidget(0, 9)
        self.comparison_table.setObjectName("comparison_table")
        self.comparison_table.setHorizontalHeaderLabels(["对齐键", "成员", "指标", "单位", "帧", "时间", "值", "缺失原因", "事件"])
        self.comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.comparison_table, 1)

        self.status = QLabel("请先提供对比成员")
        self.status.setObjectName("comparison_status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("comparison_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @staticmethod
    def _member_list(object_name: str) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName(object_name)
        widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        return widget

    def set_project(self, project: ProjectManager | None) -> None:
        self._stop_worker()
        self._stop_table_fill()
        self._cancel_export()
        self._generation += 1
        self.project = project
        self._context_id = str(project.manifest.get("project_id", "")) if project else ""
        self.set_members(())
        self.status.setText("已打开项目；请载入或选择对比成员" if project else "请先打开项目")

    def set_members(self, members: tuple[ComparisonMember, ...] | list[ComparisonMember]) -> None:
        self._stop_worker()
        self._stop_table_fill()
        self._generation += 1
        self._members = tuple(members)
        self._service = ComparisonService(self._members)
        self.report = None
        self.comparison_table.setRowCount(0)
        for widget in (self.project_selector, self.person_selector, self.trial_selector):
            widget.clear()
        self._fill_selector(self.project_selector, sorted({member.project_id for member in self._members}))
        self._fill_selector(self.person_selector, sorted({member.person_id for member in self._members}))
        self._fill_selector(self.trial_selector, sorted({member.trial_id for member in self._members}))
        self._set_export_enabled(False)
        if self._members:
            self.status.setText(f"已载入 {len(self._members)} 个对比成员，请确认筛选条件")
        else:
            self.status.setText("请先提供对比成员")

    @staticmethod
    def _fill_selector(widget: QListWidget, values: list[str]) -> None:
        for value in values:
            item = QListWidgetItem(value)
            widget.addItem(item)
            item.setSelected(True)

    def build_report(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("对比报告正在生成")
            return
        if self._service is None or not self._members:
            self.status.setText("请先提供对比成员")
            return
        try:
            request = ComparisonRequest(
                self._selected(self.project_selector),
                self._selected(self.person_selector),
                self._selected(self.trial_selector),
                self.alignment_selector.currentData(),
            )
        except ValueError as exc:
            self.status.setText(f"对比选择无效：{exc}")
            return
        self._generation += 1
        generation = self._generation
        context_id = self._context_id or "memory"
        self.build_button.setEnabled(False)
        self.status.setText("正在后台生成对比报告…")
        self._thread = QThread(self)
        self._worker = _ComparisonWorker(context_id, generation, self._service, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._report_finished)
        self._worker.failed.connect(self._report_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @staticmethod
    def _selected(widget: QListWidget) -> tuple[str, ...]:
        return tuple(item.text() for item in widget.selectedItems())

    @Slot(str, int, object)
    def _report_finished(self, context_id: str, generation: int, report: object) -> None:
        if context_id != (self._context_id or "memory") or generation != self._generation:
            return
        if not isinstance(report, ComparisonReport):
            self.status.setText("对比报告返回了无效结果")
            return
        self.report = report
        self._fill_table(report)
        self._set_export_enabled(True)
        self.summary.setText(
            f"{len(report.member_ids)} 个成员 · {len(report.rows)} 行 · {report.metadata.get('alignment_source')} · "
            f"报告版本 {report.report_version}"
        )
        self.status.setText("对比报告生成完成")

    @Slot(str, int, str)
    def _report_failed(self, context_id: str, generation: int, reason: str) -> None:
        if context_id == (self._context_id or "memory") and generation == self._generation:
            self.status.setText(f"对比报告生成失败：{reason}")

    def _fill_table(self, report: ComparisonReport) -> None:
        self._stop_table_fill()
        self.comparison_table.setRowCount(0)
        self._pending_rows = report.rows
        self._fill_position = 0
        if self._pending_rows:
            self._fill_timer.start()

    def _append_table_chunk(self) -> None:
        end = min(self._fill_position + 100, len(self._pending_rows))
        for row_data in self._pending_rows[self._fill_position:end]:
            row = self.comparison_table.rowCount()
            self.comparison_table.insertRow(row)
            values = row_data.to_dict()
            display = (
                values["alignment_key"],
                values["member_id"],
                values["metric"],
                values["unit"],
                values["frame"],
                values["time"],
                values["value"],
                values["missing_reason"],
                values["event_id"],
            )
            for column, value in enumerate(display):
                self.comparison_table.setItem(row, column, QTableWidgetItem("—" if value is None else str(value)))
        self._fill_position = end
        if self._fill_position >= len(self._pending_rows):
            self._fill_timer.stop()
            self._pending_rows = ()
            self._fill_position = 0

    def _stop_table_fill(self) -> None:
        self._fill_timer.stop()
        self._pending_rows = ()
        self._fill_position = 0

    def export_report(self, path: Path, format: str) -> None:
        if self.report is None:
            self.status.setText("请先生成对比报告")
            return
        if self.controller is not None and self.project is not None and self.controller.current_project is self.project:
            report = self.report
            destination = Path(path)
            request = TaskRequest(
                str(self.project.manifest["project_id"]),
                self.controller.generation,
                "comparison-export",
                {"path": str(destination), "format": format},
            )

            def work(token):
                token.raise_if_cancelled()
                ReportExporter().export(report, destination, format)
                token.raise_if_cancelled()
                return destination

            self._export_handle = self.controller.start_task(request, work)
            self._export_timer.start()
            self.status.setText(f"正在后台导出 {format.upper()}…")
            return
        ReportExporter().export(self.report, Path(path), format)
        self.status.setText(f"已导出 {format.upper()}：{path}")

    def _poll_export(self) -> None:
        handle = self._export_handle
        if handle is None:
            self._export_timer.stop()
            return
        try:
            result = handle.wait(0)
        except TimeoutError:
            return
        self._export_timer.stop()
        self._export_handle = None
        if self.project is None:
            return
        project_id = str(self.project.manifest.get("project_id", ""))
        generation = self.controller.generation if self.controller is not None else -1
        if result.project_id != project_id or result.generation != generation:
            return
        if result.status == "succeeded":
            self.status.setText(f"导出完成：{result.value}")
        elif result.status == "cancelled":
            self.status.setText("报告导出已取消")
        else:
            self.status.setText(f"报告导出失败：{result.error or result.status}")

    def _cancel_export(self) -> None:
        if self._export_handle is not None:
            self._export_handle.cancel()
        self._export_handle = None
        self._export_timer.stop()

    def _choose_export(self, format: str) -> None:
        if self.report is None:
            self.status.setText("请先生成对比报告")
            return
        if self.project is None:
            self.status.setText("未打开项目，默认导出未执行；请显式指定导出路径")
            return
        default_path = self.project.root / "reports" / "comparisons" / f"{self.report.report_id}.{format}"
        self.export_report(default_path, format)

    def _set_export_enabled(self, enabled: bool) -> None:
        for name in ("export_json_button", "export_csv_button", "export_html_button"):
            getattr(self, name).setEnabled(enabled)

    def _thread_finished(self) -> None:
        self.build_button.setEnabled(True)
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
        self._cancel_export()
        self._stop_table_fill()
        self._stop_worker()
        event.accept()
