import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.pages.pipeline_page import PipelinePage
from scripts.real_data_acceptance import run_acceptance


class ExistingResultsAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_data_only_trial_is_registered_reported_and_opened(self) -> None:
        source = Path("tests/fixtures/real_data").resolve()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "acceptance"

            result = run_acceptance(source, output)

            existing = result["existing_results"]
            self.assertGreaterEqual(existing["discovered_trial_count"], 1)
            self.assertFalse(existing["has_video"])
            self.assertGreater(existing["quality_2d_detection_people_count"], 0)
            self.assertTrue(existing["config_valid"])
            self.assertIn("poseEstimation", existing["general_pose2sim_stages"])
            registered_root = Path(existing["registered_root"])
            window = MainWindow()
            self.assertTrue(window.open_project_path(registered_root))
            pipeline = window._pages["pipeline"]
            self.assertIsInstance(pipeline, PipelinePage)
            self.assertTrue(pipeline.run_current_button.isEnabled())
            self.assertTrue(
                all(
                    "video_path" not in camera
                    for camera in window.project.manifest["cameras"]
                )
            )
            window.close()


if __name__ == "__main__":
    unittest.main()
