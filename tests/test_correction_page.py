import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QSplitter

from app.gui.pages.correction_page import CorrectionPage


class CorrectionPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_dense_correction_workspace_uses_adjustable_splitters_and_scrollable_details(self) -> None:
        page = CorrectionPage()
        page.resize(1120, 720)
        page.show()
        self.application.processEvents()

        workspace = page.findChild(QSplitter, "correction_workspace_splitter")
        views = page.findChild(QSplitter, "correction_views_splitter")
        details = page.findChild(QScrollArea, "correction_details_scroll")

        self.assertIsNotNone(workspace)
        self.assertIsNotNone(views)
        self.assertIsNotNone(details)
        self.assertEqual(details.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for object_name in (
            "correction_previous_button",
            "correction_next_button",
            "correction_undo_button",
            "correction_redo_button",
            "correction_reset_button",
            "correction_save_button",
            "correction_save_rerun_button",
        ):
            self.assertIsNotNone(page.findChild(object, object_name))
        page.close()

    def test_narrow_window_keeps_action_bar_and_allows_details_to_scroll(self) -> None:
        page = CorrectionPage()
        page.resize(620, 480)
        page.show()
        self.application.processEvents()

        details = page.findChild(QScrollArea, "correction_details_scroll")
        self.assertIsNotNone(details)
        assert details is not None
        self.assertTrue(details.widget().minimumHeight() >= 480)
        self.assertTrue(page.findChild(object, "correction_action_bar").isVisible())
        page.close()


if __name__ == "__main__":
    unittest.main()
