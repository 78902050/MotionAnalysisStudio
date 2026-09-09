"""Scrollable quality issue page with semantic correction navigation."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore
from app.quality.viewer import QualityComparisonView, QualityViewerModel

from ..layout import make_scrollable_panel


_SEVERITY_TEXT = {
    "info": "提示",
    "warning": "警告",
    "error": "错误",
    "blocking": "阻塞",
}
_DISPOSITION_TEXT = {
    "pending": "待处理",
    "handled": "已处理",
    "deferred": "已延期",
    "ignored": "已忽略",
}


class _QualityPageBase(QWidget):
    target_requested = Signal(object)

    def __init__(
        self,
        title: str,
        description: str,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project: ProjectManager | None = None
        self.viewer_model: QualityViewerModel | None = None
        self._build_ui(title, description)
        if project is not None:
            self.set_project(project)

    def _build_ui(self, title: str, description: str) -> None:
        body = QWidget()
        body.setObjectName("quality_page_content")
        body.setMinimumSize(920, 600)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setProperty("uiRole", "pageTitle")
        header.addWidget(heading)
        header.addStretch(1)
        self.report_version = QLabel("报告版本：—")
        self.report_version.setObjectName("quality_report_version")
        self.report_version.setProperty("uiRole", "accent")
        header.addWidget(self.report_version)
        layout.addLayout(header)

        subtitle = QLabel(description)
        subtitle.setWordWrap(True)
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(subtitle)

        comparison = QFrame()
        comparison.setObjectName("quality_comparison_strip")
        comparison.setProperty("uiRole", "recessedPanel")
        comparison_layout = QGridLayout(comparison)
        comparison_layout.setContentsMargins(12, 10, 12, 10)
        comparison_layout.setHorizontalSpacing(18)
        comparison_layout.addWidget(self._comparison_title("修改前指标"), 0, 0)
        comparison_layout.addWidget(self._comparison_title("当前指标"), 0, 1)
        comparison_layout.addWidget(self._comparison_title("最近重跑"), 0, 2)
        self.before_metrics = self._comparison_value("quality_before_metrics")
        self.current_metrics = self._comparison_value("quality_current_metrics")
        self.last_rerun = self._comparison_value("quality_last_rerun")
        comparison_layout.addWidget(self.before_metrics, 1, 0)
        comparison_layout.addWidget(self.current_metrics, 1, 1)
        comparison_layout.addWidget(self.last_rerun, 1, 2)
        comparison_layout.setColumnStretch(0, 2)
        comparison_layout.setColumnStretch(1, 2)
        comparison_layout.setColumnStretch(2, 1)
        layout.addWidget(comparison)

        issue_heading = QLabel("质量问题")
        issue_heading.setProperty("uiRole", "sectionTitle")
        layout.addWidget(issue_heading)
        self.issue_table = QTableWidget(0, 7)
        self.issue_table.setObjectName("quality_issue_table")
        self.issue_table.setHorizontalHeaderLabels(
            ["问题 ID", "严重度", "处理状态", "修改次数", "说明", "置信度/误差", "定位"]
        )
        self.issue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.issue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.issue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.issue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.issue_table.setMinimumHeight(270)
        self.issue_table.cellClicked.connect(self._request_row_target)
        layout.addWidget(self.issue_table, 1)

        self.location_status = QLabel("点击问题可定位到二维修正；不可定位的问题会在此说明原因。")
        self.location_status.setObjectName("quality_location_status")
        self.location_status.setWordWrap(True)
        self.location_status.setProperty("uiRole", "muted")
        layout.addWidget(self.location_status)

        scroll = make_scrollable_panel(body)
        scroll.setObjectName("quality_page_scroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @staticmethod
    def _comparison_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("uiRole", "eyebrow")
        return label

    @staticmethod
    def _comparison_value(object_name: str) -> QLabel:
        label = QLabel("—")
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def set_project(self, project: ProjectManager | None) -> None:
        self.project = project
        if project is None:
            self._clear("请先打开项目")
            return
        try:
            report = QualityReportStore(project).load_current()
        except FileNotFoundError:
            self._clear("当前项目尚无质量报告")
            return
        except (OSError, ValueError, KeyError) as exc:
            self._clear(f"质量报告无法读取：{exc}")
            return
        self.set_report(report, project.manifest)

    def set_report(
        self,
        report: QualityReport,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        self.viewer_model = QualityViewerModel(report)
        comparison = QualityComparisonView.from_sources(report, manifest or {})
        self.report_version.setText(f"报告版本：{comparison.current_report_id}")
        self.before_metrics.setText(
            _format_metrics(comparison.before_metrics, "暂无修改前快照")
        )
        self.current_metrics.setText(_format_metrics(comparison.current_metrics, "暂无当前指标"))
        self.last_rerun.setText(_format_timestamp(comparison.last_rerun_at))
        self._fill_issues()
        self.location_status.setText(
            f"已载入 {len(self.viewer_model.issues)} 个问题；点击可定位问题进入二维修正。"
        )

    def _fill_issues(self) -> None:
        self.issue_table.setRowCount(0)
        if self.viewer_model is None:
            return
        for issue in self.viewer_model.issues:
            row = self.issue_table.rowCount()
            self.issue_table.insertRow(row)
            location = issue.location_error or _target_text(issue.target)
            values = (
                issue.issue_id,
                _SEVERITY_TEXT.get(issue.severity, issue.severity),
                _DISPOSITION_TEXT.get(issue.disposition, issue.disposition),
                str(issue.modification_count),
                issue.message,
                _issue_measurement(issue.evidence),
                location,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, issue.issue_id)
                if issue.location_error is not None:
                    item.setForeground(Qt.GlobalColor.gray)
                self.issue_table.setItem(row, column, item)

    def _request_row_target(self, row: int, _column: int) -> None:
        if self.viewer_model is None:
            return
        item = self.issue_table.item(row, 0)
        if item is None:
            return
        issue_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(issue_id, str):
            return
        target = self.viewer_model.target(issue_id)
        if target is None:
            reason = self.viewer_model.unlocatable_reason(issue_id) or "定位信息不完整"
            self.location_status.setText(f"无法定位 {issue_id}：{reason}")
            return
        self.location_status.setText(f"正在定位 {issue_id}：{_target_text(target)}")
        self.target_requested.emit(target)

    def _clear(self, reason: str) -> None:
        self.viewer_model = None
        self.issue_table.setRowCount(0)
        self.report_version.setText("报告版本：—")
        self.before_metrics.setText("暂无修改前快照")
        self.current_metrics.setText("暂无当前指标")
        self.last_rerun.setText("尚未重跑")
        self.location_status.setText(reason)


class Quality2DPage(_QualityPageBase):
    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "二维质量检查",
            "逐帧检查 Pose2Sim 二维关节点的置信度。每项明确列出相机、原始帧、人物和关节点；点击后直接进入人工二维修正。默认低置信度阈值为 0.500。",
            project,
            parent,
        )

    def set_report(
        self,
        report: QualityReport,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        two_dimensional = tuple(
            issue
            for issue in report.issues()
            if issue.kind in {"low_confidence", "missing", "reprojection", "mapping_missing"}
            or (
                issue.kind == "input_invalid"
                and issue.evidence.get("layer") == "pose"
            )
        )
        super().set_report(
            QualityReport(
                report.report_id,
                report.generated_at,
                report.metrics_data,
                two_dimensional,
                report.inputs,
            ),
            manifest,
        )


def _format_metrics(metrics: Mapping[str, object], empty_text: str) -> str:
    if not metrics:
        return empty_text
    return " · ".join(f"{name}: {_format_value(value)}" for name, value in sorted(metrics.items()))


def _format_value(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _format_timestamp(value: str | None) -> str:
    if value is None:
        return "尚未重跑"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


def _issue_measurement(evidence: Mapping[str, object]) -> str:
    confidence = evidence.get("confidence")
    threshold = evidence.get("threshold")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
            return f"{float(confidence):.3f} < {float(threshold):.3f}"
        return f"{float(confidence):.3f}"
    error = evidence.get("error")
    if isinstance(error, (int, float)) and not isinstance(error, bool):
        return f"{float(error):.3f} px"
    return "—"


def _target_text(target: object) -> str:
    if target is None:
        return "不可定位"
    frame_label = "原始帧" if target.address.timeline == "raw" else "帧"
    person_label = (
        f"人物 {target.person.raw_person_index + 1}"
        if target.person.raw_person_index is not None
        else target.person.project_person_id
    )
    return (
        f"{target.address.camera} · {frame_label} {target.address.frame} · "
        f"{person_label} · {target.keypoint.keypoint_name}"
    )
