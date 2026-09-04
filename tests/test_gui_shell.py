import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QSplitter

from app.gui.main_window import MainWindow
from app.project.manager import ProjectManager


class GuiShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_all_pages_are_registered_and_layout_uses_adjustable_splitter(self) -> None:
        window = MainWindow()

        self.assertIn("quality_3d", window.page_ids)
        self.assertIn("correction_2d", window.page_ids)
        self.assertIsNotNone(window.findChild(QSplitter, "workspace_splitter"))
        self.assertGreaterEqual(len(window.findChildren(QScrollArea)), 1)
        self.assertLessEqual(window.minimumWidth(), 620)
        self.assertLessEqual(window.minimumHeight(), 480)

    def test_narrow_window_keeps_content_accessible_through_scroll_area(self) -> None:
        window = MainWindow()
        window.resize(620, 480)
        window.show()
        self.application.processEvents()

        scroll_areas = window.findChildren(QScrollArea)
        self.assertTrue(scroll_areas)
        self.assertTrue(
            any(area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded for area in scroll_areas)
        )
        self.assertTrue(window.navigate("quality_3d"))
        self.assertIsNotNone(window.current_page)

    def test_open_project_updates_context_without_exposing_absolute_path_in_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "中文项目", "试验一")
            window = MainWindow()

            window.open_project(project)

            self.assertIs(window.project, project)
            self.assertIn("试验一", window.project_label.text())
            self.assertNotIn(str(project.root), window.windowTitle())

    def test_close_request_is_allowed_when_no_unsaved_changes_exist(self) -> None:
        window = MainWindow()

        self.assertTrue(window.request_close_with_unsaved_guard())


if __name__ == "__main__":
    unittest.main()
