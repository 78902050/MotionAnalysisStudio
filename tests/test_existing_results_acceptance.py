import os
import tempfile
import unittest
from pathlib import Path
import shutil

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.pages.analysis_page import AnalysisPage
from app.gui.pages.correction_page import CorrectionPage
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
            self.assertIn("source_camera_count", existing)
            self.assertGreaterEqual(existing["source_camera_count"], 1)
            self.assertIn("source_video_camera_count", existing)
            self.assertFalse(existing["has_video"])
            self.assertGreater(existing["quality_2d_detection_people_count"], 0)
            self.assertGreater(existing["quality_3d_total_points"], 0)
            self.assertGreater(existing["quality_3d_valid_points"], 0)
            self.assertEqual(existing["pose_browser_camera"], "cam01")
            self.assertEqual(existing["pose_browser_frame"], 0)
            self.assertGreater(existing["pose_browser_person_count"], 0)
            self.assertEqual(existing["pose_browser_keypoint_count"], 26)
            self.assertGreater(existing["trajectory_count"], 0)
            self.assertTrue(existing["config_valid"])
            self.assertIn("poseEstimation", existing["general_pose2sim_stages"])
            registered_root = Path(existing["registered_root"])
            window = MainWindow()
            self.assertTrue(window.open_project_path(registered_root))
            pipeline = window._pages["pipeline"]
            self.assertIsInstance(pipeline, PipelinePage)
            self.assertTrue(pipeline.run_current_button.isEnabled())
            correction = window._pages["correction_2d"]
            self.assertIsInstance(correction, CorrectionPage)
            self.assertIsNotNone(correction.session)
            self.assertEqual(correction.camera_selector.currentText(), "cam01")
            self.assertGreater(correction.person_selector.count(), 0)
            self.assertEqual(correction.keypoint_selector.count(), 26)
            analysis = window._pages["analysis"]
            self.assertIsInstance(analysis, AnalysisPage)
            self.assertGreater(analysis.trajectory_selector.count(), 0)
            self.assertTrue(
                all(
                    "video_path" not in camera
                    for camera in window.project.manifest["cameras"]
                )
            )
            window.close()

    def test_pose2sim_marker_video_is_decoded_when_original_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(Path("tests/fixtures/real_data"), source)
            pose_directory = next(source.rglob("cam01_json")).parent
            video = pose_directory / "cam01_pose.mp4"
            writer = cv2.VideoWriter(
                str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (32, 24)
            )
            self.assertTrue(writer.isOpened())
            writer.write(np.full((24, 32, 3), 90, dtype=np.uint8))
            writer.release()

            result = run_acceptance(source, root / "acceptance")

            existing = result["existing_results"]
            self.assertEqual(existing["correction_video_kind"], "pose2sim_overlay")
            self.assertTrue(existing["correction_frame_decoded"])
            self.assertGreater(existing["correction_skeleton_edges"], 0)

    def test_existing_trajectory_is_ready_for_native_3d_playback(self) -> None:
        source = Path("tests/fixtures/real_data").resolve()
        with tempfile.TemporaryDirectory() as directory:
            result = run_acceptance(source, Path(directory) / "acceptance")

            playback = result["playback_3d"]
            self.assertIn(playback["format"], {"trc", "c3d"})
            self.assertGreater(playback["frame_count"], 1)
            self.assertGreater(playback["marker_count"], 1)
            self.assertGreater(playback["skeleton_edge_count"], 1)
            self.assertIn("ghost_frame_count", playback)
            self.assertGreater(playback["ghost_frame_count"], 0)
            self.assertIn("ghost_world_displacement", playback)
            self.assertGreater(playback["ghost_world_displacement"], 0)
            self.assertIsInstance(playback["diagnostics"], list)
            self.assertLess(playback["max_heartbeat_gap_ms"], 250)


if __name__ == "__main__":
    unittest.main()
