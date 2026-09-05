"""Three-dimensional quality overview page."""

from PySide6.QtWidgets import QWidget

from app.project.manager import ProjectManager

from .quality_2d_page import _QualityPageBase


class Quality3DPage(_QualityPageBase):
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
