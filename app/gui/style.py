"""Compatibility entry point for the application theme."""

from PySide6.QtCore import QSettings

from .theme import apply_theme, load_ui_preferences


def apply_style(application, settings: QSettings | None = None) -> None:
    source = settings or QSettings("MotionAnalysisStudio", "MotionAnalysisStudio")
    apply_theme(application, load_ui_preferences(source))
