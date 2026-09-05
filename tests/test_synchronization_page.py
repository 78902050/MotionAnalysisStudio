import os
import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtTest import QTest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.gui.pages.synchronization_page import SynchronizationPage
from app.application.controller import ApplicationController
from app.project.manager import ProjectManager


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
        self.assertIsNotNone(page.findChild(QLabel, "synchronization_trust_value"))
        page.close()

    def test_mapping_analysis_runs_in_supervised_background_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "后台同步")
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.save_manifest()
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps({"offsets": [{"camera": "cam01", "frame_delta": 2}]}),
                encoding="utf-8",
            )
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = SynchronizationPage(project, controller=controller)

            self.assertIn("后台", page.status.text())
            for _ in range(100):
                self.application.processEvents()
                if page.raw_frame_value.text() == "2":
                    break
                QTest.qWait(10)

            self.assertEqual(page.raw_frame_value.text(), "2")
            self.assertEqual(page.mapping_trust.text(), "verified_mapping")
            self.assertTrue(any(item.name == "synchronization-analysis" for item in controller.supervisor.snapshots()))
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()


if __name__ == "__main__":
    unittest.main()
