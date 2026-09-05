import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton
from PySide6.QtTest import QTest

from app.application.controller import ApplicationController
from app.gui.pages.calibration_page import CalibrationPage
from app.project.manager import ProjectManager


class CalibrationPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_calibration_page_exposes_import_active_file_and_diagnostics(self) -> None:
        page = CalibrationPage()

        self.assertIsNotNone(page.findChild(QPushButton, "calibration_import_button"))
        self.assertIsNotNone(page.findChild(QListWidget, "calibration_diagnostics_list"))
        self.assertIsNotNone(page.findChild(object, "calibration_active_path"))
        page.close()

    def test_real_toml_is_previewed_before_explicit_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "标定预览")
            page = CalibrationPage(project)
            source = Path("tests/fixtures/real_data/calibration/camera_array.toml")

            page.preview_file(source)

            self.assertIn("caliscope_toml", page.preview_source.text())
            self.assertIn("1, 2, 3, 4", page.preview_cameras.text())
            self.assertTrue(page.activate_button.isEnabled())
            self.assertNotIn("已激活", page.preview_status.text())

            page.activate_preview()

            self.assertIn("已激活", page.preview_status.text())
            self.assertTrue((project.root / project.manifest["calibration"]["active_path"]).is_file())
            page.close()

    def test_preview_uses_supervised_background_task_when_controller_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "后台标定预览")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = CalibrationPage(project, controller=controller)

            page.preview_file(Path("tests/fixtures/real_data/calibration/camera_array.toml"))

            self.assertIn("后台", page.preview_status.text())
            for _ in range(100):
                self.application.processEvents()
                if page.activate_button.isEnabled():
                    break
                QTest.qWait(10)
            self.assertTrue(page.activate_button.isEnabled())
            self.assertTrue(any(item.name == "calibration-preview" for item in controller.supervisor.snapshots()))
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()


if __name__ == "__main__":
    unittest.main()
