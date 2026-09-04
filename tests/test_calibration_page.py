import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton

from app.gui.pages.calibration_page import CalibrationPage


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


if __name__ == "__main__":
    unittest.main()
