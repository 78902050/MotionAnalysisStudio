import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from app.gui.main_window import MainWindow
from app.gui.pages.association_page import AssociationPage


class AssociationPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_main_window_registers_association_page_with_confirmation_actions(self) -> None:
        window = MainWindow()

        page = window._pages["association"]

        self.assertIsInstance(page, AssociationPage)
        self.assertIsNotNone(page.findChild(QTableWidget, "association_candidate_table"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_confirm_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_materialize_button"))
        self.assertIsNotNone(page.findChild(QPushButton, "association_restore_button"))


if __name__ == "__main__":
    unittest.main()
