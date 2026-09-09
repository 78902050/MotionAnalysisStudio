"""Application-wide color palettes and readable font preferences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


ThemeName = Literal["light", "dark", "system"]
ResolvedThemeName = Literal["light", "dark"]
MIN_FONT_POINT_SIZE = 10
MAX_FONT_POINT_SIZE = 16
DEFAULT_FONT_POINT_SIZE = 12


@dataclass(frozen=True)
class ThemePalette:
    name: ResolvedThemeName
    window: str
    panel: str
    recessed: str
    text: str
    muted_text: str
    border: str
    accent: str
    selection: str
    warning: str
    error: str
    canvas: str
    canvas_grid: str
    canvas_left: str
    canvas_right: str
    canvas_center: str


@dataclass(frozen=True)
class UiPreferences:
    theme: ThemeName = "light"
    font_point_size: int = DEFAULT_FONT_POINT_SIZE


LIGHT_PALETTE = ThemePalette(
    "light",
    "#F4F7FA",
    "#FFFFFF",
    "#EAF0F4",
    "#17212B",
    "#506273",
    "#C7D2DC",
    "#087F8C",
    "#CDEBED",
    "#9A6700",
    "#B42318",
    "#F8FAFC",
    "#CBD5E1",
    "#1769AA",
    "#C2410C",
    "#087F8C",
)

DARK_PALETTE = ThemePalette(
    "dark",
    "#18222D",
    "#23313D",
    "#16212B",
    "#F5F8FA",
    "#C1CED8",
    "#435666",
    "#58C7C2",
    "#27565B",
    "#F5C451",
    "#FF8A80",
    "#101A23",
    "#344858",
    "#4DA3FF",
    "#FF8A4C",
    "#58C7C2",
)


def _normalized_theme(value: object) -> ThemeName:
    name = str(value).strip().casefold()
    return name if name in {"light", "dark", "system"} else "light"  # type: ignore[return-value]


def _normalized_font_size(value: object) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = DEFAULT_FONT_POINT_SIZE
    return max(MIN_FONT_POINT_SIZE, min(MAX_FONT_POINT_SIZE, size))


def load_ui_preferences(settings: QSettings) -> UiPreferences:
    return UiPreferences(
        _normalized_theme(settings.value("ui/theme", "light")),
        _normalized_font_size(settings.value("ui/font_point_size", DEFAULT_FONT_POINT_SIZE)),
    )


def save_ui_preferences(settings: QSettings, preferences: UiPreferences) -> None:
    normalized = UiPreferences(
        _normalized_theme(preferences.theme),
        _normalized_font_size(preferences.font_point_size),
    )
    settings.setValue("ui/theme", normalized.theme)
    settings.setValue("ui/font_point_size", normalized.font_point_size)
    settings.sync()


def palette_for_name(name: str) -> ThemePalette:
    return DARK_PALETTE if str(name).casefold() == "dark" else LIGHT_PALETTE


def resolve_palette(theme: ThemeName, application: QApplication) -> ThemePalette:
    if theme != "system":
        return palette_for_name(theme)
    try:
        is_dark = application.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except (AttributeError, RuntimeError):
        is_dark = False
    return DARK_PALETTE if is_dark else LIGHT_PALETTE


def build_stylesheet(palette: ThemePalette, font_point_size: int = DEFAULT_FONT_POINT_SIZE) -> str:
    title_size = min(MAX_FONT_POINT_SIZE + 7, font_point_size + 7)
    section_size = min(MAX_FONT_POINT_SIZE + 3, font_point_size + 3)
    utility_size = max(MIN_FONT_POINT_SIZE, font_point_size - 1)
    return f"""
QMainWindow, QWidget {{
    background: {palette.window};
    color: {palette.text};
}}
QFrame#project_bar, QFrame#side_panel, QFrame#status_strip,
QFrame[uiRole="panel"] {{
    background: {palette.panel};
    border: 1px solid {palette.border};
}}
QWidget[uiRole="pageTitle"], QLabel[uiRole="pageTitle"] {{
    color: {palette.text};
    font-size: {title_size}pt;
    font-weight: 700;
}}
QWidget[uiRole="sectionTitle"], QLabel[uiRole="sectionTitle"] {{
    color: {palette.text};
    font-size: {section_size}pt;
    font-weight: 700;
}}
QWidget[uiRole="muted"], QLabel[uiRole="muted"] {{ color: {palette.muted_text}; }}
QWidget[uiRole="accent"], QLabel[uiRole="accent"] {{ color: {palette.accent}; font-weight: 650; }}
QWidget[uiRole="eyebrow"], QLabel[uiRole="eyebrow"] {{
    color: {palette.accent};
    font-size: {utility_size}pt;
    font-weight: 700;
}}
QWidget[uiRole="warning"], QLabel[uiRole="warning"] {{ color: {palette.warning}; }}
QWidget[uiRole="error"], QLabel[uiRole="error"] {{ color: {palette.error}; }}
QFrame[uiRole="recessedPanel"] {{
    background: {palette.recessed};
    border: 1px solid {palette.border};
    border-radius: 5px;
}}
QLabel#eyebrow {{ color: {palette.accent}; font-size: {utility_size}pt; font-weight: 700; }}
QLabel#project_label {{ color: {palette.text}; font-size: {section_size}pt; font-weight: 700; }}
QListWidget, QTreeWidget, QTableWidget, QTableView, QPlainTextEdit, QTextEdit,
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {palette.recessed};
    color: {palette.text};
    border: 1px solid {palette.border};
    selection-background-color: {palette.selection};
    selection-color: {palette.text};
}}
QHeaderView::section {{
    background: {palette.panel};
    color: {palette.text};
    border: 1px solid {palette.border};
    padding: 6px;
}}
QListWidget {{ outline: none; padding: 8px; }}
QListWidget::item {{ padding: 9px 10px; margin: 2px 0; border-radius: 5px; }}
QListWidget::item:selected {{ background: {palette.selection}; color: {palette.text}; }}
QPushButton, QToolButton {{
    background: {palette.panel};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 4px;
    padding: 7px 11px;
}}
QPushButton:hover, QToolButton:hover {{ background: {palette.selection}; border-color: {palette.accent}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {palette.muted_text}; background: {palette.recessed}; }}
QPushButton:focus, QToolButton:focus, QListWidget:focus, QLineEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {palette.accent}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {palette.window}; }}
QSplitter::handle {{ background: {palette.border}; }}
QSplitter::handle:hover {{ background: {palette.accent}; }}
QStatusBar {{ background: {palette.recessed}; color: {palette.muted_text}; }}
QFrame#playback_header {{ background: {palette.panel}; border: 1px solid {palette.border}; border-radius: 6px; }}
QWidget#trajectory_canvas {{ border: 1px solid {palette.border}; border-radius: 4px; }}
QLabel#playback_diagnostics {{ color: {palette.muted_text}; padding-top: 8px; }}
QToolTip {{ background: {palette.panel}; color: {palette.text}; border: 1px solid {palette.border}; }}
"""


def apply_theme(application: QApplication, preferences: UiPreferences) -> ThemePalette:
    normalized = UiPreferences(
        _normalized_theme(preferences.theme),
        _normalized_font_size(preferences.font_point_size),
    )
    palette = resolve_palette(normalized.theme, application)
    font = QFont(application.font())
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "sans-serif"])
    font.setPointSize(normalized.font_point_size)
    application.setFont(font)
    application.setProperty("masTheme", palette.name)
    application.setProperty("masFontPointSize", normalized.font_point_size)
    application.setStyleSheet(build_stylesheet(palette, normalized.font_point_size))
    return palette


def palette_for_application(application: QApplication | None = None) -> ThemePalette:
    current = application or QApplication.instance()
    if current is None:
        return LIGHT_PALETTE
    return palette_for_name(str(current.property("masTheme") or "light"))
