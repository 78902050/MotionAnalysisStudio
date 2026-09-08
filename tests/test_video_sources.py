import tempfile
import unittest
from pathlib import Path

from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter
from app.project.manager import ProjectManager

from app.media.video_sources import CameraVideoSource, VideoSourceResolver


class VideoSourceResolverTests(unittest.TestCase):
    def _project(self, root: Path, **camera_fields: object) -> ProjectManager:
        project = ProjectManager.create(root, "视频来源")
        project.manifest["cameras"] = [{"camera_id": "cam01", **camera_fields}]
        project.save_manifest()
        return project

    def test_original_is_default_and_missing_original_falls_back_to_pose2sim_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "cam01.mp4"
            overlay = root / "cam01_pose.mp4"
            original.write_bytes(b"original")
            overlay.write_bytes(b"overlay")
            project = self._project(
                root / "project",
                video_path=str(original),
                pose_video_path=str(overlay),
            )

            self.assertEqual(
                VideoSourceResolver.resolve(project)["cam01"],
                CameraVideoSource("cam01", original.resolve(), "original"),
            )
            original.unlink()
            self.assertEqual(
                VideoSourceResolver.resolve(project)["cam01"],
                CameraVideoSource("cam01", overlay.resolve(), "pose2sim_overlay"),
            )

    def test_explicit_pose2sim_preference_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "cam01.mp4"
            overlay = root / "cam01_pose.mp4"
            original.touch()
            overlay.touch()
            project = self._project(
                root / "project",
                video_path=str(original),
                pose_video_path=str(overlay),
                preferred_video_kind="pose2sim_overlay",
            )

            self.assertEqual(VideoSourceResolver.resolve(project)["cam01"].kind, "pose2sim_overlay")

    def test_relative_manifest_paths_resolve_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文项目"
            project = self._project(root, video_path="videos/cam01.mp4")
            video = root / "videos" / "cam01.mp4"
            video.parent.mkdir(exist_ok=True)
            video.touch()

            self.assertEqual(VideoSourceResolver.resolve(project)["cam01"].path, video.resolve())


class ImportedVideoSourceTests(unittest.TestCase):
    def test_importer_maps_pose2sim_video_by_camera_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory) / "走路"
            pose_json = trial / "pose" / "cam02_json"
            pose_json.mkdir(parents=True)
            (pose_json / "cam02_000000.json").write_text('{"people": []}', encoding="utf-8")
            overlay = trial / "pose" / "cam02_pose.mp4"
            overlay.write_bytes(b"pose2sim")

            candidate = ExistingResultDiscovery().discover_one(trial)
            project = ExistingResultImporter().register(candidate)
            cameras = {item["camera_id"]: item for item in project.manifest["cameras"]}

            self.assertEqual(cameras["cam02"]["pose_video_path"], str(overlay.resolve()))

    def test_refresh_preserves_existing_original_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory) / "走路"
            pose_json = trial / "pose" / "cam01_json"
            pose_json.mkdir(parents=True)
            (pose_json / "cam01_000000.json").write_text('{"people": []}', encoding="utf-8")
            (trial / "pose" / "cam01_pose.mp4").write_bytes(b"pose2sim")
            original = trial / "手工绑定.mp4"
            original.write_bytes(b"original")
            discovery = ExistingResultDiscovery()
            importer = ExistingResultImporter()
            project = importer.register(discovery.discover_one(trial))
            project.manifest["cameras"][0]["video_path"] = str(original.resolve())
            project.save_manifest()

            refreshed = importer.register(discovery.discover_one(trial))

            self.assertEqual(refreshed.manifest["cameras"][0]["video_path"], str(original.resolve()))


if __name__ == "__main__":
    unittest.main()
