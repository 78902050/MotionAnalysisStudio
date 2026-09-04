"""Non-blocking review page for human-confirmed person association."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.association.analyzer import AssociationAnalyzer
from app.association.materializer import AssociationMaterializer
from app.association.model import AssociationReport
from app.association.overrides import AssociationOverrideStore
from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore

from ..layout import make_scrollable_panel


class _AssociationWorker(QObject):
    finished = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(self, project: ProjectManager, generation: int) -> None:
        super().__init__()
        self.project = project
        self.generation = generation

    @Slot()
    def run(self) -> None:
        try:
            try:
                quality_report = QualityReportStore(self.project).load_current()
            except (OSError, ValueError, KeyError):
                quality_report = QualityReport.create("quality-unavailable", {}, (), {})
            report = AssociationAnalyzer().analyze(self.project, quality_report)
        except Exception as exc:  # returned to the GUI as a visible task failure
            self.failed.emit(self.project.manifest.get("project_id", ""), self.generation, f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(self.project.manifest.get("project_id", ""), self.generation, report)


class AssociationPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project: ProjectManager | None = None
        self.report: AssociationReport | None = None
        self._generation = 0
        self._project_id = ""
        self._thread: QThread | None = None
        self._worker: _AssociationWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading = QLabel("多人身份关联")
        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
        layout.addWidget(heading)
        description = QLabel(
            "候选只用于人工确认；确认前不会写入关联结果。表格保留相机、同步帧、检测人物和解释。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #aab9c4; font-size: 14px;")
        layout.addWidget(description)

        toolbar = QHBoxLayout()
        self.refresh_button = QPushButton("扫描关联候选")
        self.refresh_button.setObjectName("association_refresh_button")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        self.status = QLabel("请先打开项目")
        self.status.setObjectName("association_status")
        self.status.setWordWrap(True)
        toolbar.addWidget(self.status, 1)
        layout.addLayout(toolbar)

        self.candidate_table = QTableWidget(0, 7)
        self.candidate_table.setObjectName("association_candidate_table")
        self.candidate_table.setHorizontalHeaderLabels(
            ["项目人物", "相机", "同步帧", "检测人物", "方法", "分数", "状态"]
        )
        self.candidate_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.candidate_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.candidate_table.horizontalHeader().setStretchLastSection(True)
        self.candidate_table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.candidate_table, 1)

        details = QWidget()
        details_layout = QFormLayout(details)
        self.selected_person = QLabel("—")
        self.selected_target = QLabel("—")
        self.selected_fingerprint = QLabel("—")
        self.selected_explanation = QLabel("—")
        self.selected_explanation.setWordWrap(True)
        details_layout.addRow("选中项目人物", self.selected_person)
        details_layout.addRow("选中目标", self.selected_target)
        details_layout.addRow("骨架指纹", self.selected_fingerprint)
        details_layout.addRow("候选解释", self.selected_explanation)
        layout.addWidget(details)

        actions = QHBoxLayout()
        self.confirm_button = QPushButton("确认选中候选")
        self.confirm_button.setObjectName("association_confirm_button")
        self.confirm_button.clicked.connect(self.confirm_selected)
        self.materialize_button = QPushButton("物化已确认关联")
        self.materialize_button.setObjectName("association_materialize_button")
        self.materialize_button.clicked.connect(self.materialize)
        self.restore_button = QPushButton("恢复上次物化")
        self.restore_button.setObjectName("association_restore_button")
        self.restore_button.clicked.connect(self.restore)
        actions.addWidget(self.confirm_button)
        actions.addWidget(self.materialize_button)
        actions.addWidget(self.restore_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("association_scroll")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def set_project(self, project: ProjectManager | None) -> None:
        self._generation += 1
        self.project = project
        self._project_id = str(project.manifest.get("project_id", "")) if project else ""
        self.report = None
        self.candidate_table.setRowCount(0)
        self._clear_selected()
        self.status.setText("已打开项目；点击“扫描关联候选”开始后台分析" if project else "请先打开项目")

    def refresh(self) -> None:
        if self.project is None:
            self.status.setText("请先打开项目")
            return
        if self._thread is not None and self._thread.isRunning():
            self.status.setText("关联扫描正在进行")
            return
        self._generation += 1
        generation = self._generation
        self._project_id = str(self.project.manifest.get("project_id", ""))
        self.status.setText("正在后台扫描 pose、pose-sync 和 pose-associated…")
        self.refresh_button.setEnabled(False)
        self._thread = QThread(self)
        self._worker = _AssociationWorker(self.project, generation)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._analysis_finished)
        self._worker.failed.connect(self._analysis_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(str, int, object)
    def _analysis_finished(self, project_id: str, generation: int, report: object) -> None:
        if project_id != self._project_id or generation != self._generation:
            return
        if not isinstance(report, AssociationReport):
            self.status.setText("关联扫描返回了无效结果")
            return
        self.report = report
        self._fill_candidates(report)
        blocking = sum(issue.severity == "blocking" for issue in report.issues)
        self.status.setText(f"已找到 {len(report.candidates)} 个候选，{len(report.track_segments)} 个轨迹段；阻塞问题 {blocking} 个")

    @Slot(str, int, str)
    def _analysis_failed(self, project_id: str, generation: int, reason: str) -> None:
        if project_id == self._project_id and generation == self._generation:
            self.status.setText(f"关联扫描失败：{reason}")

    def _thread_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _fill_candidates(self, report: AssociationReport) -> None:
        self.candidate_table.setRowCount(0)
        for candidate in report.candidates:
            row = self.candidate_table.rowCount()
            self.candidate_table.insertRow(row)
            values = (
                candidate.project_person_id,
                candidate.camera,
                str(candidate.synchronized_frame),
                str(candidate.raw_person_index),
                candidate.method,
                f"{candidate.score:.2f}",
                "已有语义关联" if candidate.exact else "待人工确认",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, candidate)
                self.candidate_table.setItem(row, column, item)

    def _selected_candidate(self) -> Any:
        rows = self.candidate_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.candidate_table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _show_selected(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._clear_selected()
            return
        self.selected_person.setText(candidate.project_person_id)
        self.selected_target.setText(
            f"{candidate.camera} / 同步帧 {candidate.synchronized_frame} / 检测人物 {candidate.raw_person_index}"
        )
        self.selected_fingerprint.setText(candidate.fingerprint.value_hash[:16])
        self.selected_explanation.setText(candidate.explanation)

    def _clear_selected(self) -> None:
        self.selected_person.setText("—")
        self.selected_target.setText("—")
        self.selected_fingerprint.setText("—")
        self.selected_explanation.setText("—")

    def confirm_selected(self) -> None:
        candidate = self._selected_candidate()
        if self.project is None or candidate is None:
            self.status.setText("请先扫描并选择一个候选")
            return
        override = AssociationOverrideStore(self.project.root).save_confirmed(candidate)
        self.status.setText(f"已确认 {override.project_person_id} 在 {override.camera} 同步帧 {override.synchronized_frame} 的关联")

    def materialize(self) -> None:
        if self.project is None or self.report is None:
            self.status.setText("请先打开项目并完成关联扫描")
            return
        constraints = AssociationOverrideStore(self.project.root).effective_constraints(self.report)
        result = AssociationMaterializer().materialize(self.project, constraints)
        self.status.setText(
            f"已物化 {len(constraints)} 个确认关联"
            if result.succeeded
            else f"物化失败：{result.error}"
        )

    def restore(self) -> None:
        if self.project is None:
            self.status.setText("请先打开项目")
            return
        result = AssociationMaterializer().restore(self.project)
        self.status.setText("已恢复上次物化前的关联结果" if result.succeeded else f"恢复失败：{result.error}")

    def closeEvent(self, event) -> None:
        self._generation += 1
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        event.accept()
