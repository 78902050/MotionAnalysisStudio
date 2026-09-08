import os
from queue import Empty
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

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
            sources = [
                base / "Camera 1.mp4",
                base / "2.mp4",
                base / "CAM-003.mov",
                base / "camera04.mkv",
            ]
            for index, source in enumerate(sources, start=1):
                source.write_bytes(f"camera-{index}".encode())
            project.manifest["cameras"] = [
                {"camera_id": "cam01"},
                {"camera_id": "cam02"},
                {"camera_id": "cam03"},
                {"camera_id": "cam04"},
            ]
            project.save_manifest()
            page = MediaPage(controller=controller)
            page.set_project(project)
            self._wait_for_idle(page)

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(path) for path in sources], "视频文件"),
            ) as choose_files:
                page.import_videos_button.click()
                self._wait_for_idle(page)

            choose_files.assert_called_once()
            self.assertEqual((project.root / "videos" / "cam01.mp4").read_bytes(), b"camera-1")
            self.assertEqual((project.root / "videos" / "cam02.mp4").read_bytes(), b"camera-2")
            self.assertEqual((project.root / "videos" / "cam03.mov").read_bytes(), b"camera-3")
            self.assertEqual((project.root / "videos" / "cam04.mkv").read_bytes(), b"camera-4")
            self.assertEqual(
                [record["video_path"] for record in project.manifest["cameras"]],
                ["videos/cam01.mp4", "videos/cam02.mp4", "videos/cam03.mov", "videos/cam04.mkv"],
            )
            self.assertIn("已导入 4 个视频", page.status.text())
            self.assertIn("已映射 4 台相机", page.status.text())
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

    def test_conflict_no_skips_existing_project_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = ProjectManager.create(base / "project", "conflict")
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.save_manifest()
            existing = project.root / "videos" / "cam01.mp4"
            existing.write_bytes(b"existing")
            source = base / "Camera 1.mp4"
            source.write_bytes(b"replacement")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = MediaPage(controller=controller)
            page.set_project(project)
            self._wait_for_idle(page)

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(source)], "视频文件"),
            ), patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.No,
            ):
                page.import_videos_button.click()
                self._wait_for_idle(page)

            self.assertEqual(existing.read_bytes(), b"existing")
            self.assertIn("跳过已有 1 个", page.status.text())
            page.close()

    def test_background_progress_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = ProjectManager.create(base / "project", "cancel")
            source = base / "cam01.mp4"
            source.write_bytes(b"video")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = MediaPage(controller=controller)
            page.set_project(project)
            self._wait_for_idle(page)
            started = threading.Event()

            def cancellable_execute(project_arg, plan, *, replace_existing, token, progress):
                del project_arg, replace_existing
                progress(1, len(plan.items), plan.items[0].source)
                started.set()
                while not token.is_cancelled:
                    time.sleep(0.005)
                token.raise_if_cancelled()

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(source)], "视频文件"),
            ), patch(
                "app.gui.pages.media_page.VideoImportService.execute",
                side_effect=cancellable_execute,
            ):
                page.import_videos_button.click()
                self.assertTrue(started.wait(1))
                page._poll()
                self.assertIn("正在导入 1/1", page.status.text())
                page.cancel_import_button.click()
                self._wait_for_idle(page)

            self.assertIn("已取消", page.status.text())
            self.assertFalse(page.cancel_import_button.isEnabled())
            page.close()

    def test_project_switch_clears_old_import_summary_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "new")
            page = MediaPage()
            page._pending_import_summary = "旧项目已导入"
            page._import_progress.put((1, 4, "old.mp4"))

            page.set_project(project)

            self.assertNotIn("旧项目", page.status.text())
            with self.assertRaises(Empty):
                page._import_progress.get_nowait()
            page.close()

    def test_late_progress_from_cancelled_project_stays_in_old_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = ProjectManager.create(base / "first", "first")
            second = ProjectManager.create(base / "second", "second")
            source = base / "cam01.mp4"
            source.write_bytes(b"video")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(first))
            page = MediaPage(controller=controller)
            page.set_project(first)
            self._wait_for_idle(page)
            started = threading.Event()
            release = threading.Event()

            def delayed_progress(project_arg, plan, *, replace_existing, token, progress):
                del project_arg, replace_existing
                started.set()
                release.wait(1)
                progress(1, len(plan.items), plan.items[0].source)
                token.raise_if_cancelled()

            with patch(
                "app.gui.pages.media_page.QFileDialog.getOpenFileNames",
                return_value=([str(source)], "视频文件"),
            ), patch(
                "app.gui.pages.media_page.VideoImportService.execute",
                side_effect=delayed_progress,
            ):
                page.import_videos_button.click()
                self.assertTrue(started.wait(1))
                old_queue = page._import_progress
                page.set_project(second)
                self.assertIsNot(page._import_progress, old_queue)
                release.set()
                self.assertTrue(controller.supervisor.wait_for_shutdown(2000))

            with self.assertRaises(Empty):
                page._import_progress.get_nowait()
            page.close()

    def test_small_window_keeps_media_actions_scrollable(self) -> None:
        page = MediaPage()
        page.resize(620, 480)
        page.show()
        self.application.processEvents()

        areas = page.findChildren(QScrollArea)
        self.assertTrue(areas)
        self.assertTrue(
            any(
                area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
                for area in areas
            )
        )
        page.close()


if __name__ == "__main__":
    unittest.main()
