import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from app.application.quality_correction_service import QualityCorrectionService
from app.gui.main_window import MainWindow
from app.gui.pages.correction_page import CorrectionPage
from app.project.discovery import ExistingResultDiscovery
from app.project.manager import ProjectManager


def _person(offset: float) -> dict[str, object]:
    values: list[float] = []
    for index in range(26):
        values.extend((offset + index, offset + index * 2, 0.8))
    return {"person_id": [-1], "pose_keypoints_2d": values}


class ExistingPoseBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_resolves_halpe26_pose_frame_without_quality_or_synchronization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "直接浏览", "直接浏览")
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.save_manifest()
            pose_path = (
                project.root / "pose" / "cam01_json" / "cam01_000012_keypoints.json"
            )
            pose_path.parent.mkdir(parents=True, exist_ok=True)
            pose_path.write_text(
                json.dumps({"version": 1.3, "people": [_person(0.0), _person(100.0)]}),
                encoding="utf-8",
            )
            service = QualityCorrectionService(project)

            resolution = service.resolve_pose_frame("cam01", 12, 1, 9)
            session = service.create_session(resolution)

            self.assertTrue(resolution.can_edit)
            self.assertIsNone(resolution.synchronized_frame)
            self.assertEqual(resolution.raw_frame, 12)
            self.assertEqual(resolution.edit_target.address.timeline, "raw")
            self.assertEqual(resolution.edit_target.person.raw_person_index, 1)
            self.assertEqual(resolution.edit_target.person.project_person_id, "raw-1")
            self.assertEqual(resolution.edit_target.keypoint.model_name, "HALPE_26")
            self.assertEqual(resolution.edit_target.keypoint.keypoint_name, "LWrist")
            self.assertEqual(
                session.document.value_at(resolution.edit_target),
                (109.0, 118.0, 0.8),
            )
            frame_pose = session.document.frame_pose()
            self.assertEqual(len(frame_pose.people), 2)
            self.assertEqual(len(frame_pose.people[1].keypoints), 26)

    def test_pose_inventory_enables_direct_camera_and_frame_browsing(self) -> None:
        page = CorrectionPage()
        requests: list[tuple[str, int, int, int]] = []
        page.browse_requested.connect(
            lambda camera, frame, person, keypoint: requests.append(
                (camera, frame, person, keypoint)
            )
        )

        page.set_pose_inventory({"cam01": (12, 15), "cam02": (4,)})

        self.assertEqual(page.camera_selector.currentText(), "cam01")
        self.assertEqual((page.timeline.minimum(), page.timeline.maximum()), (12, 15))
        self.assertEqual(requests[-1], ("cam01", 12, 0, 0))
        self.assertIsInstance(page.person_selector, QComboBox)
        self.assertIsInstance(page.keypoint_selector, QComboBox)
        page.close()

    def test_opening_project_displays_first_existing_pose_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "直接显示", "直接显示")
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.save_manifest()
            pose_path = project.root / "pose" / "cam01_json" / "cam01_000012.json"
            pose_path.parent.mkdir(parents=True, exist_ok=True)
            pose_path.write_text(
                json.dumps({"version": 1.3, "people": [_person(0.0)]}),
                encoding="utf-8",
            )
            window = MainWindow()
            try:
                self.assertTrue(window.open_project(project))

                page = window._pages["correction_2d"]
                self.assertIsNone(page.session)
                self.assertFalse(window.project_loading_progress.isHidden())
                for _ in range(100):
                    self.application.processEvents()
                    if page.session is not None:
                        break
                    time.sleep(0.01)

                self.assertIsNotNone(page.session)
                self.assertEqual(page.timeline.value(), 12)
                self.assertEqual(page.person_selector.count(), 1)
                self.assertEqual(page.keypoint_selector.count(), 26)
                self.assertEqual(page._canvases[0].point_count, 26)
                self.assertIn("直接浏览", page.session_status.text())
                self.assertTrue(window.project_loading_progress.isHidden())
            finally:
                window.close()

    def test_switching_projects_cancels_an_old_pose_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = ProjectManager.create(root / "first", "first")
            first.manifest["cameras"] = [{"camera_id": "cam-old"}]
            first.save_manifest()
            second = ProjectManager.create(root / "second", "second")
            second.manifest["cameras"] = [{"camera_id": "cam-new"}]
            second.save_manifest()
            original = ExistingResultDiscovery.pose_frame_inventory
            first_scan_started = False

            def delayed_inventory(path, layer="pose", **kwargs):
                nonlocal first_scan_started
                if Path(path) == first.root and layer == "pose":
                    first_scan_started = True
                    cancelled = kwargs.get("cancelled")
                    deadline = time.monotonic() + 1.0
                    while time.monotonic() < deadline:
                        if callable(cancelled) and cancelled():
                            return {}
                        time.sleep(0.01)
                return original(path, layer, **kwargs)

            window = MainWindow()
            try:
                with patch.object(
                    ExistingResultDiscovery,
                    "pose_frame_inventory",
                    side_effect=delayed_inventory,
                ):
                    self.assertTrue(window.open_project(first))
                    deadline = time.monotonic() + 1.0
                    while not first_scan_started and time.monotonic() < deadline:
                        self.application.processEvents()
                        time.sleep(0.01)
                    self.assertTrue(first_scan_started)
                    self.assertTrue(window.open_project(second, dirty_decision="discard"))
                    deadline = time.monotonic() + 2.0
                    while window._project_loading_project_id and time.monotonic() < deadline:
                        self.application.processEvents()
                        time.sleep(0.01)

                self.assertFalse(window._project_loading_project_id)
                page = window._pages["correction_2d"]
                self.assertEqual(page.camera_selector.currentText(), "cam-new")
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
