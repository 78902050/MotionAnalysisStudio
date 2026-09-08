import tempfile
import unittest
from pathlib import Path

from app.media.importer import VideoImportService
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken, TaskCancelled


class _CancelDuringCopyToken(CancellationToken):
    def __init__(self) -> None:
        super().__init__()
        self._checks = 0

    def raise_if_cancelled(self) -> None:
        self._checks += 1
        if self._checks == 2:
            self.cancel()
        super().raise_if_cancelled()


class VideoImportServiceTests(unittest.TestCase):
    def test_project_creation_includes_videos_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"

            ProjectManager.create(root, "Video import")

            self.assertTrue((root / "videos").is_dir())

    def test_plan_matches_numeric_camera_aliases_and_targets_project_videos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            project.manifest["cameras"] = [
                {"camera_id": "cam01"},
                {"camera_id": "cam02"},
            ]
            camera_one = root / "Camera 1.mp4"
            camera_two = root / "2.mp4"
            camera_one.write_bytes(b"camera-one")
            camera_two.write_bytes(b"camera-two")

            plan = VideoImportService.plan(project, [camera_one, camera_two])

            self.assertEqual(
                [(item.camera, item.destination.name) for item in plan.items],
                [("cam01", "cam01.mp4"), ("cam02", "cam02.mp4")],
            )
            self.assertEqual(
                tuple(item.match_method for item in plan.items),
                ("semantic", "semantic"),
            )
            self.assertFalse(plan.requires_confirmation)

    def test_plan_creates_camera_from_stem_when_manifest_has_no_cameras(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            source = root / "left.mp4"
            source.write_bytes(b"left-camera")

            plan = VideoImportService.plan(project, [source])

            self.assertEqual(len(plan.items), 1)
            self.assertEqual(plan.items[0].camera, "left")
            self.assertEqual(plan.items[0].destination, root / "videos" / "left.mp4")
            self.assertEqual(plan.items[0].match_method, "new_camera")
            self.assertFalse(plan.requires_confirmation)

    def test_equal_unresolved_counts_use_natural_order_and_require_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            project.manifest["cameras"] = [
                {"camera_id": "cam10"},
                {"camera_id": "cam2"},
            ]
            view_ten = root / "view10.mp4"
            view_two = root / "view2.mp4"
            view_ten.write_bytes(b"ten")
            view_two.write_bytes(b"two")

            plan = VideoImportService.plan(project, [view_ten, view_two])

            self.assertEqual(
                [(item.source.name, item.camera) for item in plan.items],
                [("view2.mp4", "cam2"), ("view10.mp4", "cam10")],
            )
            self.assertEqual(
                tuple(item.match_method for item in plan.items),
                ("ordered", "ordered"),
            )
            self.assertTrue(plan.requires_confirmation)

    def test_duplicate_semantic_aliases_are_not_treated_as_unique_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            project.manifest["cameras"] = [
                {"camera_id": "cam01"},
                {"camera_id": "cam02"},
            ]
            first = root / "first" / "Camera 1.mp4"
            second = root / "second" / "cam1.mp4"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            plan = VideoImportService.plan(project, [first, second])

            self.assertEqual(
                tuple(item.match_method for item in plan.items),
                ("ordered", "ordered"),
            )
            self.assertEqual(
                tuple(item.camera for item in plan.items),
                ("cam01", "cam02"),
            )
            self.assertTrue(plan.requires_confirmation)

    def test_unequal_unresolved_counts_are_unmatched_and_not_assigned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            project.manifest["cameras"] = [
                {"camera_id": "cam01"},
                {"camera_id": "cam02"},
            ]
            source = root / "unknown.mp4"
            source.write_bytes(b"unknown")

            plan = VideoImportService.plan(project, [source])

            self.assertEqual(plan.items, ())
            self.assertEqual(plan.unmatched_files, (source.resolve(),))
            self.assertFalse(plan.requires_confirmation)
            self.assertTrue(plan.warnings)

    def test_plan_filters_unsupported_and_derived_videos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            video = root / "clip.MP4"
            derived = root / "clip_pose.mp4"
            unsupported = root / "notes.txt"
            for path in (video, derived, unsupported):
                path.write_bytes(path.name.encode("utf-8"))

            plan = VideoImportService.plan(project, [unsupported, derived, video])

            self.assertEqual(tuple(item.source for item in plan.items), (video.resolve(),))
            self.assertEqual(plan.items[0].destination.name, "clip.MP4")
            self.assertEqual(
                plan.unmatched_files,
                (unsupported.resolve(), derived.resolve()),
            )

    def test_plan_marks_duplicate_destinations_as_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            first = root / "first" / "left.mp4"
            second = root / "second" / "left.mp4"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            plan = VideoImportService.plan(project, [first, second])

            self.assertEqual(
                tuple(item.conflict for item in plan.items),
                (True, True),
            )

    def test_plan_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = ProjectManager.create(root, "Video import")
            missing = root / "missing.mp4"

            with self.assertRaisesRegex(FileNotFoundError, "video file not found"):
                VideoImportService.plan(project, [missing])

    def test_execute_copies_chinese_path_and_binds_project_relative_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "中文项目"
            source_dir = base / "外部 视频"
            source_dir.mkdir()
            source = source_dir / "左侧.MP4"
            original = b"\x00\x01unchanged-video\xff"
            source.write_bytes(original)
            project = ProjectManager.create(root, "步态分析")
            plan = VideoImportService.plan(project, [source])
            progress: list[tuple[int, int, Path]] = []

            result = VideoImportService.execute(
                project,
                plan,
                replace_existing=False,
                token=CancellationToken(),
                progress=lambda completed, total, path: progress.append(
                    (completed, total, path)
                ),
            )

            destination = root / "videos" / "左侧.MP4"
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(result.imported, (destination,))
            self.assertEqual(result.bound_cameras, ("左侧",))
            self.assertEqual(result.skipped, ())
            self.assertEqual(
                project.manifest["cameras"],
                [{"camera_id": "左侧", "video_path": "videos/左侧.MP4"}],
            )
            self.assertEqual(progress, [(1, 1, source.resolve())])

    def test_execute_skips_or_replaces_existing_destination_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            project = ProjectManager.create(root, "Video import")
            source = base / "cam01.mp4"
            source.write_bytes(b"new-video")
            destination = root / "videos" / "cam01.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"old-video")
            plan = VideoImportService.plan(project, [source])
            self.assertTrue(plan.items[0].conflict)

            skipped = VideoImportService.execute(
                project,
                plan,
                replace_existing=False,
                token=CancellationToken(),
            )

            self.assertEqual(destination.read_bytes(), b"old-video")
            self.assertEqual(skipped.imported, ())
            self.assertEqual(skipped.skipped, (destination,))
            self.assertEqual(skipped.bound_cameras, ("cam01",))

            replaced = VideoImportService.execute(
                project,
                plan,
                replace_existing=True,
                token=CancellationToken(),
            )

            self.assertEqual(destination.read_bytes(), b"new-video")
            self.assertEqual(source.read_bytes(), b"new-video")
            self.assertEqual(replaced.imported, (destination,))
            self.assertEqual(replaced.skipped, ())

    def test_cancellation_removes_active_temporary_file_and_does_not_bind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "project"
            project = ProjectManager.create(root, "Video import")
            source = base / "cam01.mp4"
            source.write_bytes(b"x" * (1024 * 1024 + 1))
            plan = VideoImportService.plan(project, [source])

            with self.assertRaises(TaskCancelled):
                VideoImportService.execute(
                    project,
                    plan,
                    replace_existing=False,
                    token=_CancelDuringCopyToken(),
                )

            videos = root / "videos"
            self.assertFalse((videos / "cam01.mp4").exists())
            self.assertEqual(tuple(videos.iterdir()), ())
            self.assertEqual(project.manifest["cameras"], [])


if __name__ == "__main__":
    unittest.main()
