import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.application.pipeline_launcher import build_pipeline_commands
from app.media.importer import VideoImportService
from app.pose2sim.config_document import ConfigDocument
from app.pose2sim.config_model import ConfigModel
from app.pose2sim.parameter_help_zh import help_for, known_parameter_paths
from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken


class VideoConfigWorkflowAcceptanceTests(unittest.TestCase):
    def test_four_video_config_and_command_workflow_stays_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "中文项目", "四机位验收")
            project.manifest["cameras"] = [
                {"camera_id": f"cam{index:02d}"} for index in range(1, 5)
            ]
            project.save_manifest()

            source_root = root / "外部素材"
            source_root.mkdir()
            videos = (
                source_root / "Camera 1.mp4",
                source_root / "2.avi",
                source_root / "CAM-003.mov",
                source_root / "camera04.mkv",
            )
            source_bytes = {}
            for index, video in enumerate(videos, start=1):
                payload = f"video-{index}".encode()
                video.write_bytes(payload)
                source_bytes[video] = payload

            plan = VideoImportService.plan(project, videos)
            result = VideoImportService.execute(
                project,
                plan,
                replace_existing=False,
                token=CancellationToken(),
            )

            self.assertEqual(len(result.imported), 4)
            self.assertEqual(result.bound_cameras, ("cam01", "cam02", "cam03", "cam04"))
            self.assertEqual(
                [record["video_path"] for record in project.manifest["cameras"]],
                [
                    "videos/cam01.mp4",
                    "videos/cam02.avi",
                    "videos/cam03.mov",
                    "videos/cam04.mkv",
                ],
            )
            self.assertTrue(all(path.read_bytes() == source_bytes[path] for path in videos))

            external_config = source_root / "Config.toml"
            external_config.write_text(
                "[project]\nframe_rate = 60\n\n[pose]\n"
                "# With RTMLib reference comment\n"
                "det_frequency = 4\n",
                encoding="utf-8",
            )
            external_before = external_config.read_bytes()
            document = ConfigDocument.open(project.path_for("config"))
            document.import_file(external_config)
            model = ConfigModel.parse(document.text, known_parameter_paths())
            updated = model.set_value(("pose", "det_frequency"), "2")
            document.save(updated, "验收参数修改")

            self.assertEqual(external_config.read_bytes(), external_before)
            self.assertIn("det_frequency = 2", project.path_for("config").read_text(encoding="utf-8"))
            tooltip = help_for(("pose", "det_frequency")).tooltip()
            self.assertIn("二维姿态估计", tooltip)
            self.assertNotIn("With RTMLib", tooltip)

            commands = build_pipeline_commands(
                project.path_for("config"),
                ("poseEstimation",),
                project_root=project.root,
                frozen=False,
            )
            command = commands["poseEstimation"]
            self.assertEqual(command[-1], str(project.root))
            self.assertIn("--pose2sim-project-root", command)


if __name__ == "__main__":
    unittest.main()
