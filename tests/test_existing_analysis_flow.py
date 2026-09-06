import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.project.manager import ProjectManager


FIXTURE_TRC = Path("tests/fixtures/real_data/pose3d/three_frames_65_markers.trc")


class ExistingAnalysisFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_existing_trc_and_mot_are_listed_and_metrics_feed_downstream_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "跨栏试次", "跨栏试次")
            trc = project.root / "pose-3d" / "trial_P0.trc"
            shutil.copy2(FIXTURE_TRC, trc)
            mot = project.root / "kinematics" / "trial_P0.mot"
            mot.write_text("Coordinates\n", encoding="utf-8")
            window = MainWindow()
            try:
                self.assertTrue(window.open_project(project))
                analysis = window._pages["analysis"]

                self.assertEqual(analysis.trajectory_selector.count(), 1)
                self.assertEqual(Path(analysis.trajectory_selector.currentData()), trc)
                self.assertEqual(analysis.kinematics_files.count(), 1)
                self.assertIn("trial_P0.mot", analysis.kinematics_files.item(0).text())

                analysis.calculate()
                deadline = time.monotonic() + 5.0
                while analysis._thread is not None and time.monotonic() < deadline:
                    self.application.processEvents()
                    time.sleep(0.01)

                events = window._pages["events"]
                comparison = window._pages["comparison"]
                self.assertIsNotNone(events.metric_table)
                self.assertEqual(len(comparison._members), 1)
                self.assertEqual(comparison._members[0].project_id, project.manifest["project_id"])
                self.assertEqual(comparison._members[0].person_id, "P0")
                self.assertEqual(comparison._members[0].trial_id, "跨栏试次")
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
