"""Scrollable quality issue page with semantic correction navigation."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.project.manager import ProjectManager
from app.domain.issues import QualityIssue
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
    _ISSUES_PER_PAGE = 200

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
        self._issue_page = 0
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
        self._content_layout = layout

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

        pagination = QHBoxLayout()
        self.previous_issue_page_button = QPushButton("上一页")
        self.previous_issue_page_button.setObjectName("quality_previous_issue_page")
        self.next_issue_page_button = QPushButton("下一页")
        self.next_issue_page_button.setObjectName("quality_next_issue_page")
        self.issue_page_label = QLabel("第 0/0 页")
        self.issue_page_label.setObjectName("quality_issue_page")
        pagination.addStretch(1)
        pagination.addWidget(self.previous_issue_page_button)
        pagination.addWidget(self.issue_page_label)
        pagination.addWidget(self.next_issue_page_button)
        self.previous_issue_page_button.clicked.connect(lambda: self._change_issue_page(-1))
        self.next_issue_page_button.clicked.connect(lambda: self._change_issue_page(1))
        layout.addLayout(pagination)

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

    def set_project(
        self,
        project: ProjectManager | None,
        *,
        load_report: bool = True,
    ) -> None:
        self.project = project
        if project is None:
            self._clear("请先打开项目")
            return
        if not load_report:
            self._clear("正在后台读取质量报告…")
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

    def show_report_unavailable(self, reason: str) -> None:
        """Show a completed background-load state without retrying disk I/O."""
        self._clear(reason)

    def set_report(
        self,
        report: QualityReport,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        self.viewer_model = QualityViewerModel(report)
        self._issue_page = 0
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
        self.issue_table.setUpdatesEnabled(False)
        self.issue_table.setRowCount(0)
        if self.viewer_model is None:
            self._update_issue_pagination(0)
            self.issue_table.setUpdatesEnabled(True)
            return
        issues = self._issues_for_display()
        total = len(issues)
        page_count = max(1, (total + self._ISSUES_PER_PAGE - 1) // self._ISSUES_PER_PAGE)
        self._issue_page = min(self._issue_page, page_count - 1)
        start = self._issue_page * self._ISSUES_PER_PAGE
        visible_issues = issues[start : start + self._ISSUES_PER_PAGE]
        self.issue_table.setRowCount(len(visible_issues))
        for row, issue in enumerate(visible_issues):
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
        self._update_issue_pagination(total)
        self.issue_table.setUpdatesEnabled(True)

    def _change_issue_page(self, offset: int) -> None:
        if self.viewer_model is None:
            return
        total = len(self._issues_for_display())
        page_count = max(1, (total + self._ISSUES_PER_PAGE - 1) // self._ISSUES_PER_PAGE)
        requested = min(max(0, self._issue_page + offset), page_count - 1)
        if requested == self._issue_page:
            return
        self._issue_page = requested
        self._fill_issues()

    def _issues_for_display(self):
        if self.viewer_model is None:
            return ()
        return self.viewer_model.issues

    def _update_issue_pagination(self, total: int) -> None:
        page_count = (total + self._ISSUES_PER_PAGE - 1) // self._ISSUES_PER_PAGE if total else 0
        current = self._issue_page + 1 if page_count else 0
        self.issue_page_label.setText(f"第 {current}/{page_count} 页 · 共 {total} 项")
        self.previous_issue_page_button.setEnabled(self._issue_page > 0)
        self.next_issue_page_button.setEnabled(
            page_count > 0 and self._issue_page < page_count - 1
        )

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
        self._issue_page = 0
        self.issue_table.setRowCount(0)
        self._update_issue_pagination(0)
        self.report_version.setText("报告版本：—")
        self.before_metrics.setText("暂无修改前快照")
        self.current_metrics.setText("暂无当前指标")
        self.last_rerun.setText("尚未重跑")
        self.location_status.setText(reason)


class Quality2DPage(_QualityPageBase):
    scan_requested = Signal()
    issues_filtered = Signal(object)
    _TWO_DIMENSIONAL_KINDS = frozenset(
        {"low_confidence", "missing", "reprojection", "mapping_missing"}
    )

    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "二维质量检查",
            "点击“开始二维质检”后逐帧检查 Pose2Sim 二维关节点的置信度。每项明确列出相机、原始帧、人物和关节点；点击后直接进入人工二维修正。默认低置信度阈值为 0.500。",
            project,
            parent,
        )
        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(6)
        filters.addWidget(QLabel("相机"), 0, 0)
        self.camera_filter = QComboBox()
        self.camera_filter.setObjectName("quality_2d_camera_filter")
        self.camera_filter.addItem("全部相机", None)
        filters.addWidget(self.camera_filter, 0, 1)
        filters.addWidget(QLabel("人物"), 0, 2)
        self.person_filter = QComboBox()
        self.person_filter.setObjectName("quality_2d_person_filter")
        self.person_filter.addItem("全部人物", None)
        filters.addWidget(self.person_filter, 0, 3)
        filters.addWidget(QLabel("关键点"), 1, 0)
        self.keypoint_filter = QComboBox()
        self.keypoint_filter.setObjectName("quality_2d_keypoint_filter")
        self.keypoint_filter.setEditable(True)
        self.keypoint_filter.lineEdit().setReadOnly(True)
        self.keypoint_filter.lineEdit().setPlaceholderText("全部关键点")
        self._replace_keypoint_options(())
        filters.addWidget(self.keypoint_filter, 1, 1)
        filters.addWidget(QLabel("帧范围"), 1, 2)
        self.frame_start_filter = QSpinBox()
        self.frame_start_filter.setObjectName("quality_2d_frame_start_filter")
        self.frame_start_filter.setRange(0, 2_147_483_647)
        self.frame_start_filter.setValue(0)
        filters.addWidget(self.frame_start_filter, 1, 3)
        filters.addWidget(QLabel("至"), 1, 4)
        self.frame_end_filter = QSpinBox()
        self.frame_end_filter.setObjectName("quality_2d_frame_end_filter")
        self.frame_end_filter.setRange(0, 2_147_483_647)
        self.frame_end_filter.setValue(2_147_483_647)
        filters.addWidget(self.frame_end_filter, 1, 5)
        filters.addWidget(QLabel("置信度"), 2, 0)
        self.confidence_operator = QComboBox()
        self.confidence_operator.setObjectName("quality_2d_confidence_operator")
        self.confidence_operator.addItem("全部", "all")
        self.confidence_operator.addItem("≤", "at_most")
        self.confidence_operator.addItem("≥", "at_least")
        filters.addWidget(self.confidence_operator, 2, 1)
        self.confidence_threshold = QDoubleSpinBox()
        self.confidence_threshold.setObjectName("quality_2d_confidence_threshold")
        self.confidence_threshold.setRange(0.0, 1.0)
        self.confidence_threshold.setDecimals(3)
        self.confidence_threshold.setSingleStep(0.05)
        self.confidence_threshold.setValue(0.5)
        filters.addWidget(self.confidence_threshold, 2, 2)
        self.apply_filters_button = QPushButton("开始筛选")
        self.apply_filters_button.setObjectName("quality_2d_apply_filters")
        filters.addWidget(self.apply_filters_button, 2, 3)
        self.reset_filters_button = QPushButton("清除筛选")
        self.reset_filters_button.setObjectName("quality_2d_reset_filters")
        filters.addWidget(self.reset_filters_button, 2, 4)
        self._content_layout.insertLayout(2, filters)

        actions = QHBoxLayout()
        self.scan_button = QPushButton("开始二维质检")
        self.scan_button.setObjectName("quality_2d_scan_button")
        self.scan_button.clicked.connect(self.scan_requested.emit)
        actions.addWidget(self.scan_button)
        actions.addStretch(1)
        self._content_layout.insertLayout(3, actions)

        self.scan_progress = QProgressBar()
        self.scan_progress.setObjectName("quality_2d_scan_progress")
        self.scan_progress.setTextVisible(True)
        self.scan_progress.setVisible(False)
        self._content_layout.insertWidget(4, self.scan_progress)
        self.camera_filter.currentIndexChanged.connect(self._mark_filters_dirty)
        self.person_filter.currentIndexChanged.connect(self._mark_filters_dirty)
        self.keypoint_filter.view().pressed.connect(self._toggle_keypoint_filter)
        self.frame_start_filter.valueChanged.connect(self._mark_filters_dirty)
        self.frame_end_filter.valueChanged.connect(self._mark_filters_dirty)
        self.confidence_operator.currentIndexChanged.connect(self._mark_filters_dirty)
        self.confidence_threshold.valueChanged.connect(self._mark_filters_dirty)
        self.apply_filters_button.clicked.connect(self._apply_filters)
        self.reset_filters_button.clicked.connect(self._reset_filters)
        if self.viewer_model is not None:
            self._refresh_filter_options()
            self._apply_filters()

    def set_scan_running(self, running: bool) -> None:
        self.scan_button.setEnabled(not running)
        self.scan_button.setText("正在检查…" if running else "开始二维质检")
        self.scan_progress.setVisible(running)
        if running:
            self.scan_progress.setRange(0, 0)
            self.scan_progress.setFormat("正在准备读取二维姿态文件…")

    def set_scan_progress(self, completed: int, total: int) -> None:
        if total <= 0:
            self.scan_progress.setRange(0, 1)
            self.scan_progress.setValue(1)
            self.scan_progress.setFormat("未发现可读取的二维姿态文件")
            return
        self.scan_progress.setRange(0, total)
        self.scan_progress.setValue(min(max(completed, 0), total))
        self.scan_progress.setFormat(
            f"正在读取 {completed}/{total} 个二维姿态文件（%p%）"
        )

    @classmethod
    def issues_for_report(cls, report: QualityReport) -> tuple[QualityIssue, ...]:
        return tuple(
            issue
            for issue in report.issues()
            if issue.kind in cls._TWO_DIMENSIONAL_KINDS
            or (
                issue.kind == "input_invalid"
                and issue.evidence.get("layer") == "pose"
            )
        )

    def set_report(
        self,
        report: QualityReport,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        two_dimensional = self.issues_for_report(report)
        self._two_dimensional_issues = two_dimensional
        if hasattr(self, "camera_filter"):
            self._filtered_issue_views = ()
            self._filtered_report_issue_cache = ()
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
        if hasattr(self, "camera_filter"):
            self._refresh_filter_options()
            self._apply_filters()

    def _refresh_filter_options(self) -> None:
        if self.viewer_model is None:
            return
        previous_camera = self.camera_filter.currentData()
        previous_person = self.person_filter.currentData()
        previous_keypoints = self._selected_keypoints()
        cameras: set[str] = set()
        keypoints: set[str] = set()
        people_from_issues: set[int] = set()
        for row in self.viewer_model.issues:
            target = row.target
            if target is None:
                continue
            cameras.add(target.address.camera)
            keypoints.add(target.keypoint.keypoint_name)
            raw_index = target.person.raw_person_index
            if isinstance(raw_index, int) and not isinstance(raw_index, bool) and raw_index >= 0:
                people_from_issues.add(raw_index)
        self._replace_filter_options(
            self.camera_filter,
            "全部相机",
            ((camera, camera) for camera in sorted(cameras, key=str.casefold)),
            previous_camera,
        )
        self._replace_filter_options(
            self.person_filter,
            "全部人物",
            (
                (f"人物 {raw_index}", raw_index)
                for raw_index in self._actual_person_indices(people_from_issues)
            ),
            previous_person,
        )
        self._replace_keypoint_options(
            sorted(keypoints, key=str.casefold),
            previous_keypoints,
        )

    @staticmethod
    def _replace_filter_options(
        combo: QComboBox,
        label: str,
        values,
        selected: object,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(label, None)
        for display, value in values:
            combo.addItem(display, value)
        selected_index = combo.findData(selected)
        combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        combo.blockSignals(False)

    def _replace_keypoint_options(
        self,
        keypoints: tuple[str, ...] | list[str],
        selected: set[str] | None = None,
    ) -> None:
        """Populate the keypoint picker with genuinely checkable choices."""
        chosen = selected or set()
        model = QStandardItemModel(self.keypoint_filter)
        all_item = QStandardItem("全部关键点")
        all_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        all_item.setData(None, Qt.ItemDataRole.UserRole)
        all_item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        model.appendRow(all_item)
        for keypoint in keypoints:
            item = QStandardItem(keypoint)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(keypoint, Qt.ItemDataRole.UserRole)
            item.setData(
                Qt.CheckState.Checked if keypoint in chosen else Qt.CheckState.Unchecked,
                Qt.ItemDataRole.CheckStateRole,
            )
            model.appendRow(item)
        self.keypoint_filter.blockSignals(True)
        self.keypoint_filter.setModel(model)
        self.keypoint_filter.setCurrentIndex(0)
        self.keypoint_filter.blockSignals(False)
        self._update_keypoint_filter_text()

    def _selected_keypoints(self) -> set[str]:
        model = self.keypoint_filter.model()
        return {
            str(self.keypoint_filter.itemData(row))
            for row in range(1, self.keypoint_filter.count())
            if model.data(model.index(row, 0), Qt.ItemDataRole.CheckStateRole)
            == Qt.CheckState.Checked
        }

    def _toggle_keypoint_filter(self, index) -> None:
        if not index.isValid():
            return
        model = self.keypoint_filter.model()
        if index.row() == 0:
            for row in range(1, self.keypoint_filter.count()):
                model.setData(
                    model.index(row, 0),
                    Qt.CheckState.Unchecked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        else:
            state = model.data(index, Qt.ItemDataRole.CheckStateRole)
            model.setData(
                index,
                (
                    Qt.CheckState.Unchecked
                    if state == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                ),
                Qt.ItemDataRole.CheckStateRole,
            )
        self._update_keypoint_filter_text()
        self._mark_filters_dirty()

    def _update_keypoint_filter_text(self) -> None:
        selected = sorted(self._selected_keypoints(), key=str.casefold)
        if not selected:
            text = "全部关键点"
        elif len(selected) == 1:
            text = selected[0]
        else:
            text = f"已选 {len(selected)} 个关键点"
        self.keypoint_filter.lineEdit().setText(text)

    def _actual_person_indices(
        self,
        fallback: set[int] | None = None,
    ) -> tuple[int, ...]:
        if self.viewer_model is None:
            return ()
        pose_input = self.viewer_model.report.inputs.get("pose_2d")
        if isinstance(pose_input, dict):
            values = pose_input.get("raw_person_indices")
            if isinstance(values, list):
                indices = {
                    value
                    for value in values
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                }
                if indices:
                    return tuple(sorted(indices))
        return tuple(sorted(fallback or ()))

    def _issues_for_display(self):
        if self.viewer_model is None or not hasattr(self, "camera_filter"):
            return super()._issues_for_display()
        return getattr(self, "_filtered_issue_views", ())

    def _matches_filters(
        self,
        address,
        person,
        keypoint_address,
        evidence: Mapping[str, object],
    ) -> bool:
        camera = self.camera_filter.currentData()
        raw_person_index = self.person_filter.currentData()
        keypoints = self._selected_keypoints()
        first_frame = self.frame_start_filter.value()
        last_frame = self.frame_end_filter.value()
        confidence_mode = self.confidence_operator.currentData()
        threshold = self.confidence_threshold.value()
        if camera is not None and (address is None or address.camera != camera):
            return False
        if raw_person_index is not None and (
            person is None or person.raw_person_index != raw_person_index
        ):
            return False
        if keypoints and (
            keypoint_address is None
            or keypoint_address.keypoint_name not in keypoints
        ):
            return False
        if first_frame > 0 or last_frame < 2_147_483_647:
            if address is None or not first_frame <= address.frame <= last_frame:
                return False
        confidence = evidence.get("confidence")
        if confidence_mode == "at_most":
            return _is_number(confidence) and float(confidence) <= threshold
        if confidence_mode == "at_least":
            return _is_number(confidence) and float(confidence) >= threshold
        return True

    def _filtered_report_issues(self) -> tuple[QualityIssue, ...]:
        if hasattr(self, "_filtered_report_issue_cache"):
            return self._filtered_report_issue_cache
        return tuple(
            issue
            for issue in getattr(self, "_two_dimensional_issues", ())
            if self._matches_filters(
                issue.target,
                issue.person,
                issue.keypoint,
                issue.evidence,
            )
        )

    def _rebuild_filtered_cache(self) -> None:
        if self.viewer_model is None:
            self._filtered_issue_views = ()
            self._filtered_report_issue_cache = ()
            return
        camera = self.camera_filter.currentData()
        raw_person_index = self.person_filter.currentData()
        keypoints = self._selected_keypoints()
        first_frame = self.frame_start_filter.value()
        last_frame = self.frame_end_filter.value()
        confidence_mode = self.confidence_operator.currentData()
        threshold = self.confidence_threshold.value()
        views = []
        issues = []
        for issue, row in zip(self._two_dimensional_issues, self.viewer_model.issues):
            target = row.target
            address = target.address if target is not None else None
            person = target.person if target is not None else None
            keypoint = target.keypoint if target is not None else None
            if not self._matches_filter_values(
                address,
                person,
                keypoint,
                row.evidence,
                camera,
                raw_person_index,
                keypoints,
                first_frame,
                last_frame,
                confidence_mode,
                threshold,
            ):
                continue
            views.append(row)
            issues.append(issue)
        self._filtered_issue_views = tuple(views)
        self._filtered_report_issue_cache = tuple(issues)

    @staticmethod
    def _matches_filter_values(
        address,
        person,
        keypoint_address,
        evidence: Mapping[str, object],
        camera: object,
        raw_person_index: object,
        keypoints: set[str],
        first_frame: int,
        last_frame: int,
        confidence_mode: object,
        threshold: float,
    ) -> bool:
        if camera is not None and (address is None or address.camera != camera):
            return False
        if raw_person_index is not None and (
            person is None or person.raw_person_index != raw_person_index
        ):
            return False
        if keypoints and (
            keypoint_address is None
            or keypoint_address.keypoint_name not in keypoints
        ):
            return False
        if first_frame > 0 or last_frame < 2_147_483_647:
            if address is None or not first_frame <= address.frame <= last_frame:
                return False
        confidence = evidence.get("confidence")
        if confidence_mode == "at_most":
            return _is_number(confidence) and float(confidence) <= threshold
        if confidence_mode == "at_least":
            return _is_number(confidence) and float(confidence) >= threshold
        return True

    def _apply_filters(self, *_ignored: object) -> None:
        if self.viewer_model is None or not hasattr(self, "camera_filter"):
            return
        self._issue_page = 0
        self._rebuild_filtered_cache()
        self._fill_issues()
        shown = len(self._filtered_issue_views)
        self.location_status.setText(
            f"筛选后显示 {shown}/{len(self.viewer_model.issues)} 个问题；已同步刷新二维修正的问题列表。"
        )
        self.issues_filtered.emit(self._filtered_report_issue_cache)

    def _mark_filters_dirty(self, *_ignored: object) -> None:
        if self.viewer_model is None or not hasattr(self, "apply_filters_button"):
            return
        self.location_status.setText(
            "筛选条件已修改；点击“开始筛选”同时刷新二维质检与二维修正的问题列表。"
        )

    def _reset_filters(self) -> None:
        controls = (
            self.camera_filter,
            self.person_filter,
            self.frame_start_filter,
            self.frame_end_filter,
            self.confidence_operator,
            self.confidence_threshold,
        )
        for control in controls:
            control.blockSignals(True)
        self.camera_filter.setCurrentIndex(0)
        self.person_filter.setCurrentIndex(0)
        self.frame_start_filter.setValue(0)
        self.frame_end_filter.setValue(2_147_483_647)
        self.confidence_operator.setCurrentIndex(0)
        self.confidence_threshold.setValue(0.5)
        for control in controls:
            control.blockSignals(False)
        self._replace_keypoint_options(
            tuple(
                str(self.keypoint_filter.itemData(row))
                for row in range(1, self.keypoint_filter.count())
            )
        )
        self._apply_filters()


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


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _target_text(target: object) -> str:
    if target is None:
        return "不可定位"
    frame_label = "原始帧" if target.address.timeline == "raw" else "帧"
    person_label = (
        f"人物 {target.person.raw_person_index}"
        if target.person.raw_person_index is not None
        else target.person.project_person_id
    )
    return (
        f"{target.address.camera} · {frame_label} {target.address.frame} · "
        f"{person_label} · {target.keypoint.keypoint_name}"
    )
