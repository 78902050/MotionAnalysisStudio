import tempfile
import unittest
from pathlib import Path

from app.external_tools.discovery import ExternalToolDiscovery


class ExternalToolDiscoveryTests(unittest.TestCase):
    @staticmethod
    def _pose2sim_environment(root: Path) -> Path:
        python = root / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        package = root / "Lib" / "site-packages" / "Pose2Sim"
        package.mkdir(parents=True)
        (package / "Pose2Sim.py").touch()
        return python

    def test_pose2sim_environment_folder_resolves_its_python_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "动作分析环境"
            python = self._pose2sim_environment(root)

            resolution = ExternalToolDiscovery.resolve_pose2sim(root)

            self.assertEqual(resolution.executable, python.resolve())
            self.assertEqual(resolution.installation_directory, root.resolve())

    def test_pose2sim_package_folder_resolves_back_to_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "venv"
            python = self._pose2sim_environment(root)
            package = root / "Lib" / "site-packages" / "Pose2Sim"

            resolution = ExternalToolDiscovery.resolve_pose2sim(package)

            self.assertEqual(resolution.executable, python.resolve())

    def test_caliscope_environment_folder_resolves_scripts_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "caliscope-env"
            executable = root / "Scripts" / "caliscope.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()

            resolution = ExternalToolDiscovery.resolve_caliscope(root)

            self.assertEqual(resolution.executable, executable.resolve())
            self.assertEqual(resolution.installation_directory, root.resolve())

    def test_missing_installation_reports_what_could_not_be_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Pose2Sim.*Python"):
                ExternalToolDiscovery.resolve_pose2sim(Path(directory))


if __name__ == "__main__":
    unittest.main()
