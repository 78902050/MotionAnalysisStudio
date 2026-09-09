import tempfile
import tomllib
import unittest
import subprocess
import sys
from pathlib import Path

from scripts.pose2sim_sample_acceptance import build_runner_command, prepare_sample


class Pose2SimSampleAcceptanceTests(unittest.TestCase):
    def test_script_can_be_invoked_directly_from_repository_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/pose2sim_sample_acceptance.py", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--sample", completed.stdout)

    def test_prepare_sample_copies_and_limits_work_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Demo_单人"
            (source / "videos").mkdir(parents=True)
            (source / "videos" / "cam01.mp4").write_bytes(b"video")
            config = source / "Config.toml"
            config.write_text(
                "[project]\nproject_dir = '.'\nframe_range = 'auto'\n"
                "[pose]\ndisplay_detection = true\noverwrite_pose = false\n"
                "save_video = 'to_video'\nparallel_workers_pose = 'auto'\n",
                encoding="utf-8",
            )
            source_config = config.read_bytes()

            prepared = prepare_sample(source, root / "work", frames=3)

            self.assertNotEqual(prepared.resolve(), source.resolve())
            self.assertEqual(config.read_bytes(), source_config)
            copied = tomllib.loads((prepared / "Config.toml").read_text(encoding="utf-8"))
            self.assertEqual(copied["project"]["frame_range"], [0, 3])
            self.assertFalse(copied["pose"]["display_detection"])
            self.assertTrue(copied["pose"]["overwrite_pose"])
            self.assertEqual(copied["pose"]["save_video"], "none")
            self.assertEqual(copied["pose"]["parallel_workers_pose"], 1)
            self.assertEqual((prepared / "videos" / "cam01.mp4").read_bytes(), b"video")

    def test_prepare_sample_requires_config_and_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty"
            source.mkdir()

            with self.assertRaisesRegex(ValueError, "Config.toml"):
                prepare_sample(source, root / "work", frames=2)

    def test_runner_command_uses_module_for_python_and_direct_cli_for_exe(self) -> None:
        arguments = ("--pose2sim-runtime-check",)

        python_command = build_runner_command(Path("C:/Python/python.exe"), arguments, force_python=True)
        frozen_command = build_runner_command(Path("C:/App/MotionAnalysisStudio.exe"), arguments)

        self.assertEqual(
            python_command,
            ("C:\\Python\\python.exe", "-m", "app.main", "--pose2sim-runtime-check"),
        )
        self.assertEqual(
            frozen_command,
            ("C:\\App\\MotionAnalysisStudio.exe", "--pose2sim-runtime-check"),
        )


if __name__ == "__main__":
    unittest.main()
