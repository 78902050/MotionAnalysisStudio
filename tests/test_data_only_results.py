import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.pages.correction_page import CorrectionCanvas
from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter
from app.project.manager import ProjectManager
from app.quality.audit import QualityAuditService


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "real_data" / "pose"


class DataOnlyResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_nested_pose2sim_frames_are_counted_by_quality_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "仅结果质检")
            shutil.copytree(FIXTURE_ROOT, root / "pose", dirs_exist_ok=True)

            report = QualityAuditService().analyze(project)

            self.assertEqual(report.metrics()["2d_detection_people_count"], 4)
            self.assertFalse(
                any(
                    issue.evidence.get("layer") == "pose"
                    for issue in report.issues()
                )
            )

    def test_canvas_uses_pose_coordinate_space_without_video_frame(self) -> None:
        canvas = CorrectionCanvas()
        canvas.resize(640, 360)

        canvas.set_pose_points({"left_wrist": (1986.0, 1017.0, 0.9)})
        canvas.set_selected_point(1986.0, 1017.0)

        self.assertFalse(canvas.has_frame)
        self.assertTrue(canvas.has_coordinate_space)
        self.assertFalse(canvas._image_rect().isEmpty())

    def test_imported_result_without_report_starts_background_quality_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory) / "已处理试次"
            shutil.copytree(FIXTURE_ROOT, trial / "pose")
            candidates = ExistingResultDiscovery().scan(trial)
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            project = ExistingResultImporter().register(candidate)
            report_path = project.path_for("quality_report")
            self.assertFalse(report_path.exists())
            window = MainWindow()

            self.assertTrue(window.open_project(project, dirty_decision="discard"))
            handle = window.initial_quality_handle
            self.assertIsNotNone(handle)
            assert handle is not None
            result = handle.wait(5)
            self.application.processEvents()

            self.assertEqual(result.status, "succeeded")
            self.assertTrue(report_path.is_file())
            self.assertEqual(result.value.metrics()["2d_detection_people_count"], 4)
            window.close()


if __name__ == "__main__":
    unittest.main()
