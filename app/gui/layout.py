"""Reusable layouts for dense, resizable workspaces."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QSplitter, QWidget


def make_scrollable_panel(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setObjectName("scrollable_panel")
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    area.setWidget(widget)
    return area


def make_resizable_splitter(*widgets: QWidget) -> QSplitter:
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(5)
    for widget in widgets:
        splitter.addWidget(widget)
    if widgets:
        splitter.setStretchFactor(0, 0)
        for index in range(1, len(widgets)):
            splitter.setStretchFactor(index, 1)
    return splitter
