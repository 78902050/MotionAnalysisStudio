import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QListWidget, QPushButton
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

    def test_active_calibration_parameters_are_visible_per_camera(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "标定参数显示")
            page = CalibrationPage(project)
            page.import_file(Path("tests/fixtures/real_data/calibration/camera_array.toml"))

            selector = page.findChild(QComboBox, "calibration_camera_selector")
            matrix = page.findChild(QLabel, "calibration_matrix_value")
            distortions = page.findChild(QLabel, "calibration_distortions_value")
            rotation = page.findChild(QLabel, "calibration_rotation_value")
            translation = page.findChild(QLabel, "calibration_translation_value")
            image_size = page.findChild(QLabel, "calibration_image_size_value")

            self.assertIsNotNone(selector)
            self.assertEqual(selector.count(), 4)
            self.assertIn("1800.764224", matrix.text())
            self.assertIn("-0.016085", distortions.text())
            self.assertIn("0.966556", rotation.text())
            self.assertIn("1.392501", translation.text())
            self.assertEqual(image_size.text(), "3840 × 2160")

            selector.setCurrentText("2")
            self.assertIn("1785.275528", matrix.text())
            self.assertIn("1.442983", translation.text())
            page.close()


if __name__ == "__main__":
    unittest.main()
