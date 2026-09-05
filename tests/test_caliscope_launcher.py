import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from app.external_tools.caliscope_settings import CaliscopeSettingsDiagnostic
from app.external_tools.launcher import ExternalToolLaunchError, ExternalToolLauncher
from app.external_tools.model import build_caliscope_command


class CaliscopeLauncherTests(unittest.TestCase):
    def test_configured_executable_builds_workspace_command_without_shell(self) -> None:
        workspace = Path("D:/测试/标定工作区")
        executable = Path("D:/Tools/caliscope.exe")

        command = build_caliscope_command(workspace, executable)

        self.assertEqual(command, (str(executable), "--workspace", str(workspace)))

    def test_environment_executable_is_used_when_setting_is_empty(self) -> None:
        workspace = Path("D:/workspace")
        with patch.dict("os.environ", {"CALISCOPE_EXECUTABLE": "D:/portable/caliscope.exe"}):
            command = build_caliscope_command(workspace)

        self.assertEqual(command[0], "D:/portable/caliscope.exe")

    def test_process_start_is_nonblocking_and_utf8_log_records_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "caliscope.log"
            command = (
                sys.executable,
                "-c",
                "import time; print('标定已启动', flush=True); time.sleep(0.2)",
            )
            started = time.monotonic()

            handle = ExternalToolLauncher().start(command, root, log_path)

            self.assertLess(time.monotonic() - started, 0.15)
            self.assertEqual(handle.wait(3), 0)
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("标定已启动", log)
            self.assertIn("exit_code=0", log)

    def test_nonzero_exit_and_missing_executable_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handle = ExternalToolLauncher().start(
                (sys.executable, "-c", "raise SystemExit(7)"),
                root,
                root / "failed.log",
            )

            self.assertEqual(handle.wait(3), 7)
            self.assertIn("exit_code=7", (root / "failed.log").read_text(encoding="utf-8"))
            with self.assertRaises(ExternalToolLaunchError):
                ExternalToolLauncher().start(
                    (str(root / "missing-caliscope.exe"),),
                    root,
                    root / "missing.log",
                )

    def test_gb18030_settings_are_backed_up_and_converted_to_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            source = 'workspace_name = "动作标定"\n'
            path.write_bytes(source.encode("gb18030"))
            diagnostic = CaliscopeSettingsDiagnostic.inspect(path)

            self.assertEqual(diagnostic.encoding, "gb18030")
            self.assertTrue(diagnostic.valid)
            backup = CaliscopeSettingsDiagnostic.convert_to_utf8(path)

            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), source.encode("gb18030"))
            self.assertEqual(tomllib.loads(path.read_text(encoding="utf-8"))["workspace_name"], "动作标定")

    def test_invalid_toml_is_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            original = b"[broken\n"
            path.write_bytes(original)

            with self.assertRaises(ValueError):
                CaliscopeSettingsDiagnostic.convert_to_utf8(path)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("settings.toml.*.bak")), [])


if __name__ == "__main__":
    unittest.main()
