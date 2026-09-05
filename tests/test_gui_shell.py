import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QSplitter

from app.gui.main_window import MainWindow
from app.gui.pages.project_page import ProjectPage
from app.gui.pages.tasks_page import TasksPage
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest


class _FailingEditor:
    def dirty_state(self):
        from app.application.dirty_state import DirtyState

        return DirtyState(True, "测试编辑器")

    def save(self) -> bool:
        return False

    def discard_unsaved(self) -> None:
        pass


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
            project.manifest["cameras"] = [
                {"camera_id": "camA"},
                {"camera_id": "camB"},
                {"camera_id": "camC"},
                {"camera_id": "camD"},
            ]
            window = MainWindow()

            window.open_project(project)

            self.assertIs(window.project, project)
            self.assertIn("试验一", window.project_label.text())
            self.assertNotIn(str(project.root), window.windowTitle())
            correction_page = window._pages["correction_2d"]
            self.assertEqual(
                [correction_page.camera_selector.itemText(index) for index in range(4)],
                ["camA", "camB", "camC", "camD"],
            )

    def test_close_request_is_allowed_when_no_unsaved_changes_exist(self) -> None:
        window = MainWindow()

        self.assertTrue(window.request_close_with_unsaved_guard())

    def test_project_and_task_pages_are_real_controller_backed_pages(self) -> None:
        window = MainWindow()

        self.assertIsInstance(window._pages["project"], ProjectPage)
        self.assertIsInstance(window._pages["tasks"], TasksPage)
        self.assertIs(window._pages["tasks"].supervisor, window.controller.supervisor)

    def test_open_project_path_updates_controller_and_project_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "项目一", "项目一")
            window = MainWindow()

            self.assertTrue(window.open_project_path(project.root))

            self.assertEqual(window.controller.current_project.root, project.root)
            self.assertIn("项目一", window._pages["project"].current_project.text())

    def test_save_failure_keeps_window_open(self) -> None:
        window = MainWindow()
        window.controller.register_editor("failing", _FailingEditor())

        with patch.object(window, "_ask_dirty_decision", return_value="save"):
            self.assertFalse(window.request_close_with_unsaved_guard())

    def test_controller_task_binds_status_strip_and_cancel_button(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "项目", "任务项目")
            window = MainWindow()
            self.assertTrue(window.open_project(project))
            started = threading.Event()

            def work(token):
                started.set()
                while not token.is_cancelled:
                    time.sleep(0.01)
                return "stopped"

            handle = window.controller.start_task(
                TaskRequest(
                    str(project.manifest["project_id"]),
                    window.controller.generation,
                    "后台校验",
                    {},
                ),
                work,
            )
            self.addCleanup(window.controller.supervisor.wait_for_shutdown, 1000)
            self.addCleanup(handle.cancel)
            self.assertTrue(started.wait(1))
            self.application.processEvents()

            self.assertTrue(window.task_strip.cancel_button.isEnabled())
            self.assertIn("后台校验", window.task_strip.label.text())
            window.task_strip.cancel_button.click()
            self.assertEqual(handle.wait(2).status, "cancelled")


if __name__ == "__main__":
    unittest.main()
