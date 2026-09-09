import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QSpinBox

from app.gui.theme import (
    UiPreferences,
    apply_theme,
    load_ui_preferences,
    palette_for_application,
    palette_for_name,
    save_ui_preferences,
)


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    bright, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


class GuiThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = QSettings(
            str(Path(self.temporary.name) / "settings.ini"),
            QSettings.Format.IniFormat,
        )

    def tearDown(self) -> None:
        apply_theme(self.application, UiPreferences("light", 12))

    def test_new_settings_default_to_light_twelve_point_text(self) -> None:
        self.assertEqual(load_ui_preferences(self.settings), UiPreferences("light", 12))

    def test_preferences_persist_and_invalid_values_are_normalized(self) -> None:
        save_ui_preferences(self.settings, UiPreferences("dark", 14))
        self.assertEqual(load_ui_preferences(self.settings), UiPreferences("dark", 14))

        self.settings.setValue("ui/theme", "unknown")
        self.settings.setValue("ui/font_point_size", 99)
        self.assertEqual(load_ui_preferences(self.settings), UiPreferences("light", 16))

        self.settings.setValue("ui/font_point_size", 2)
        self.assertEqual(load_ui_preferences(self.settings).font_point_size, 10)

    def test_light_and_dark_text_contrast_meets_normal_text_threshold(self) -> None:
        for name in ("light", "dark"):
            with self.subTest(name=name):
                palette = palette_for_name(name)
                self.assertGreaterEqual(_contrast(palette.text, palette.window), 4.5)
                self.assertGreaterEqual(_contrast(palette.text, palette.panel), 4.5)

    def test_apply_theme_updates_application_font_stylesheet_and_palette(self) -> None:
        palette = apply_theme(self.application, UiPreferences("dark", 14))

        self.assertEqual(palette.name, "dark")
        self.assertEqual(self.application.font().pointSize(), 14)
        self.assertEqual(self.application.property("masTheme"), "dark")
        self.assertIn(palette.window, self.application.styleSheet())
        self.assertEqual(palette_for_application(self.application), palette)

    def test_settings_page_persists_theme_and_font_controls(self) -> None:
        from app.gui.pages.settings_page import SettingsPage

        page = SettingsPage(settings=self.settings)
        theme = page.findChild(QComboBox, "settings_theme")
        font_size = page.findChild(QSpinBox, "settings_font_size")

        self.assertIsNotNone(theme)
        self.assertIsNotNone(font_size)
        self.assertEqual(theme.currentData(), "light")
        self.assertEqual(font_size.value(), 12)

        theme.setCurrentIndex(theme.findData("dark"))
        font_size.setValue(14)
        self.assertTrue(page.save_settings())
        page.close()

        restored = SettingsPage(settings=self.settings)
        self.assertEqual(restored.findChild(QComboBox, "settings_theme").currentData(), "dark")
        self.assertEqual(restored.findChild(QSpinBox, "settings_font_size").value(), 14)
        restored.close()

    def test_main_window_applies_saved_visual_settings_immediately(self) -> None:
        from app.gui.main_window import MainWindow

        with patch("app.gui.main_window.QSettings", return_value=self.settings):
            window = MainWindow()
        page = window._pages["settings"]
        page.theme_selector.setCurrentIndex(page.theme_selector.findData("dark"))
        page.font_size.setValue(14)

        self.assertTrue(page.save_settings())
        self.application.processEvents()

        self.assertEqual(self.application.property("masTheme"), "dark")
        self.assertEqual(self.application.font().pointSize(), 14)
        window.close()

    def test_representative_pages_expose_semantic_visual_roles(self) -> None:
        from app.gui.pages.correction_page import CorrectionPage
        from app.gui.pages.pipeline_page import PipelinePage
        from app.gui.pages.project_page import ProjectPage
        from app.gui.pages.quality_2d_page import Quality2DPage
        from app.gui.pages.settings_page import SettingsPage

        cases = (
            (ProjectPage(), "项目工作区", "pageTitle"),
            (PipelinePage(), "Pose2Sim 流程", "pageTitle"),
            (Quality2DPage(), "二维质量检查", "pageTitle"),
            (CorrectionPage(), "二维修正", "pageTitle"),
            (SettingsPage(settings=self.settings), "设置", "pageTitle"),
        )
        for page, label_text, role in cases:
            with self.subTest(page=type(page).__name__):
                labels = [label for label in page.findChildren(QLabel) if label.text() == label_text]
                self.assertEqual(len(labels), 1)
                self.assertEqual(labels[0].property("uiRole"), role)
            page.close()

        quality = Quality2DPage()
        comparison = quality.findChild(QFrame, "quality_comparison_strip")
        self.assertIsNotNone(comparison)
        self.assertEqual(comparison.property("uiRole"), "recessedPanel")
        quality.close()


if __name__ == "__main__":
    unittest.main()
