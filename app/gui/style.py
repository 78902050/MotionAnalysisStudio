"""Visual tokens for the motion-analysis desktop workspace."""

APP_STYLE = """
QMainWindow, QWidget {
    background: #111923;
    color: #e7edf2;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}
QFrame#project_bar, QFrame#side_panel, QFrame#status_strip {
    background: #182531;
    border: 1px solid #2a3c4b;
}
QLabel#eyebrow {
    color: #75d7c7;
    font-size: 11px;
    font-weight: 700;
}
QLabel#project_label {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
}
QListWidget {
    background: #15212b;
    border: none;
    outline: none;
    padding: 8px;
}
QListWidget::item {
    padding: 9px 10px;
    margin: 2px 0;
    border-radius: 5px;
}
QListWidget::item:selected {
    background: #1f5b60;
    color: #ffffff;
}
QPushButton, QToolButton {
    background: #23404d;
    border: 1px solid #3b6673;
    border-radius: 4px;
    padding: 7px 11px;
}
QPushButton:hover, QToolButton:hover {
    background: #2d5963;
}
QPushButton:focus, QToolButton:focus, QListWidget:focus {
    border: 2px solid #75d7c7;
}
QScrollArea {
    background: #111923;
}
QSplitter::handle {
    background: #2a3c4b;
}
QSplitter::handle:hover {
    background: #75d7c7;
}
QStatusBar {
    background: #0d141c;
    color: #aab9c4;
}
"""


def apply_style(application) -> None:
    application.setStyleSheet(APP_STYLE)
