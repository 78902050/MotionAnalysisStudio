import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from app.application.controller import ApplicationController
from app.gui.pages.media_page import MediaPage
from app.project.manager import ProjectManager


class VideoImportGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _wait_for_idle(self, page: MediaPage, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while page._handle is not None and time.monotonic() < deadline:
            self.application.processEvents()
            page._poll()
            time.sleep(0.01)
        self.assertIsNone(page._handle)

    def test_import_videos_copies_multiple_files_and_reports_bound_cameras(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = ProjectManager.create(base / "项目", "视频分析")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            first = base / "Camera 1.mp4"
            second = base / "2.mp4"
            first.write_bytes(b"camera-one")
            second.write_bytes(b"camera-two")
            project.manifest["cameras"] = [
                {"camera_id": "cam01"},
                {"camera_id": "cam02"},
            ]
            project.save_manifest()
            page = MediaPage(controller=controller)
            page.set_project(project)
            self._wait_for_idle(page)

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(first), str(second)], "视频文件"),
            ) as choose_files:
                page.import_videos_button.click()
                self._wait_for_idle(page)

            choose_files.assert_called_once()
            self.assertEqual((project.root / "videos" / "cam01.mp4").read_bytes(), b"camera-one")
            self.assertEqual((project.root / "videos" / "cam02.mp4").read_bytes(), b"camera-two")
            self.assertEqual(
                [record["video_path"] for record in project.manifest["cameras"]],
                ["videos/cam01.mp4", "videos/cam02.mp4"],
            )
            self.assertIn("已导入 2 个视频", page.status.text())
            self.assertIn("已映射 2 台相机", page.status.text())
            self.assertNotIn("未使用视频", page.status.text())
            page.close()

    def test_ordered_mapping_requires_confirmation_and_cancel_has_no_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = ProjectManager.create(base / "project", "ordered")
            project.manifest["cameras"] = [{"camera_id": "cam01"}, {"camera_id": "cam02"}]
            project.save_manifest()
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            first = base / "left.mp4"
            second = base / "right.mp4"
            first.write_bytes(b"left")
            second.write_bytes(b"right")
            page = MediaPage(controller=controller)
            page.set_project(project)
            self._wait_for_idle(page)

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(first), str(second)], "视频文件"),
            ), patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.No,
            ) as confirm:
                page.import_videos_button.click()

            confirm.assert_called_once()
            self.assertEqual(tuple((project.root / "videos").iterdir()), ())
            self.assertTrue(all("video_path" not in record for record in project.manifest["cameras"]))
            page.close()


if __name__ == "__main__":
    unittest.main()
