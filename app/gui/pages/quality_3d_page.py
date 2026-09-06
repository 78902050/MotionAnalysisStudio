"""Three-dimensional quality overview and playback navigation page."""

from typing import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QWidget

from app.project.manager import ProjectManager
from app.quality.model import QualityReport

from .quality_2d_page import _QualityPageBase


class Quality3DPage(_QualityPageBase):
    playback_requested = Signal(str, int)

    def __init__(
        self,
        project: ProjectManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "三维质量检查",
            "对照重跑前后指标与当前三维质量问题。报告保持只读；具有完整二维语义定位的问题可直接进入人工修正。",
            project,
            parent,
        )
        self.playback_button = QPushButton("在三维回放中打开")
        self.playback_button.setObjectName("quality_open_playback")
        self.playback_button.setEnabled(False)
        self.playback_button.clicked.connect(self.open_in_playback)
        body_layout = self.location_status.parentWidget().layout()
        body_layout.insertWidget(body_layout.indexOf(self.location_status), self.playback_button)
        self.issue_table.itemSelectionChanged.connect(self._update_playback_action)
        self._update_playback_action()

    def set_report(
        self,
        report: QualityReport,
        manifest: Mapping[str, object] | None = None,
    ) -> None:
        super().set_report(report, manifest)
        self._update_playback_action()

    def select_issue(self, issue_id: str) -> bool:
        for row in range(self.issue_table.rowCount()):
            item = self.issue_table.item(row, 0)
            if item is not None and item.text() == issue_id:
                self.issue_table.selectRow(row)
                self._update_playback_action()
                return True
        return False

    def _selected_target(self):
        if self.viewer_model is None:
            return None
        rows = self.issue_table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        item = self.issue_table.item(rows[0].row(), 0)
        return self.viewer_model.target(item.text()) if item is not None else None

    def _update_playback_action(self) -> None:
        if not hasattr(self, "playback_button"):
            return
        target = self._selected_target()
        valid = bool(
            target is not None
            and target.address.frame >= 0
            and target.person.project_person_id.strip()
        )
        self.playback_button.setEnabled(valid)

    def open_in_playback(self) -> None:
        target = self._selected_target()
        if target is None or target.address.frame < 0:
            self.location_status.setText("所选问题缺少可用的三维人物或帧定位")
            self.playback_button.setEnabled(False)
            return
        person_id = target.person.project_person_id.strip()
        if not person_id:
            self.location_status.setText("所选问题缺少人物定位信息")
            self.playback_button.setEnabled(False)
            return
        self.location_status.setText(
            f"正在打开三维回放：{person_id} · 帧 {target.address.frame}"
        )
        self.playback_requested.emit(person_id, target.address.frame)
