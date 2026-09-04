import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.gui.pages.synchronization_page import SynchronizationPage


class SynchronizationPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_page_separates_sync_and_raw_frame_fields_and_exposes_override_action(self) -> None:
        page = SynchronizationPage()

        self.assertIsNotNone(page.findChild(QLabel, "synchronization_frame_value"))
        self.assertIsNotNone(page.findChild(QLabel, "raw_frame_value"))
        self.assertIsNotNone(page.findChild(QPushButton, "synchronization_override_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "synchronization_refresh_button"))
        page.close()


if __name__ == "__main__":
    unittest.main()
