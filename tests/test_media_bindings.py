import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.gui.pages.media_page import MediaPage, MediaRecord
from app.media.bindings import VideoBindingService
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken


class MediaBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _project(self, root: Path) -> ProjectManager:
        project = ProjectManager.create(root / "project", "绑定测试")
        project.manifest["cameras"] = [
            {"camera_id": "cam01", "note": "keep"},
            {"camera_id": "cam02", "note": "untouched"},
        ]
        project.save_manifest()
        return project

    def test_binding_updates_only_selected_camera_and_preserves_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            video = root / "相机二.mp4"
            video.write_bytes(b"unchanged media bytes")
            before = video.read_bytes()

            source = VideoBindingService.bind(project, "cam02", video, "original")

            self.assertEqual(source.camera, "cam02")
            self.assertNotIn("video_path", project.manifest["cameras"][0])
            self.assertEqual(project.manifest["cameras"][1]["video_path"], str(video.resolve()))
            self.assertEqual(project.manifest["cameras"][1]["note"], "untouched")
            self.assertEqual(video.read_bytes(), before)

    def test_clear_removes_only_requested_kind_and_updates_preference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            original = root / "cam01.mp4"
            overlay = root / "cam01_pose.mp4"
            original.touch()
            overlay.touch()
            VideoBindingService.bind(project, "cam01", original, "original")
            VideoBindingService.bind(project, "cam01", overlay, "pose2sim_overlay", preferred=True)

            VideoBindingService.clear(project, "cam01", "pose2sim_overlay")

            record = project.manifest["cameras"][0]
            self.assertEqual(record["video_path"], str(original.resolve()))
            self.assertNotIn("pose_video_path", record)
            self.assertEqual(record["preferred_video_kind"], "original")

    def test_media_page_reports_selected_pose2sim_source_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            overlay = root / "cam01_pose.mp4"
            overlay.touch()
            VideoBindingService.bind(project, "cam01", overlay, "pose2sim_overlay")
            page = MediaPage(project)

            records = page._scan_project(project, CancellationToken())

            self.assertEqual(records[0].source_kind, "pose2sim_overlay")
            self.assertEqual(records[0].source_label, "Pose2Sim 二维标记视频")
            self.assertIsNotNone(page.findChild(QPushButton, "media_import_videos"))
            page.close()

    def test_binding_rejects_unknown_camera_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            with self.assertRaisesRegex(KeyError, "cam99"):
                VideoBindingService.bind(project, "cam99", Path(directory) / "x.mp4", "original")
            with self.assertRaises(FileNotFoundError):
                VideoBindingService.bind(project, "cam01", Path(directory) / "x.mp4", "original")

    def test_folder_import_binds_unique_camera_matches_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            videos = root / "源视频"
            videos.mkdir()
            cam01 = videos / "cam01.mp4"
            cam01.touch()
            (videos / "cam01_pose.mp4").touch()
            (videos / "cam02-front.mp4").touch()
            (videos / "cam02-side.mp4").touch()
            (videos / "other.mp4").touch()

            result = VideoBindingService.bind_directory(project, videos, "original")

            self.assertEqual(tuple(source.camera for source in result.bound), ("cam01",))
            self.assertEqual(result.bound[0].path, cam01.resolve())
            self.assertEqual(result.unmatched_cameras, ())
            self.assertEqual(tuple(result.ambiguous), ("cam02",))
            self.assertEqual(project.manifest["cameras"][0]["video_path"], str(cam01.resolve()))
            self.assertNotIn("video_path", project.manifest["cameras"][1])

    def test_media_page_exposes_single_analysis_video_import(self) -> None:
        page = MediaPage()

        self.assertEqual(page.import_videos_button.text(), "导入视频")
        self.assertIsNotNone(page.findChild(QPushButton, "media_import_videos"))
        self.assertEqual(page.prefer_original_button.text(), "优先分析视频")
        page.close()

    def test_original_source_is_labeled_as_analysis_video(self) -> None:
        record = MediaRecord("cam01", "x.mp4", 30.0, "1920 × 1080", 1.0, source_kind="original")

        self.assertEqual(record.source_label, "分析视频")


if __name__ == "__main__":
    unittest.main()
