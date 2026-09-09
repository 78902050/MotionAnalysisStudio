import unittest
import subprocess
import tempfile
from pathlib import Path


class SmokeScriptWaitTests(unittest.TestCase):
    def test_smoke_script_waits_for_windowed_executable_and_checks_exit_code(self) -> None:
        script = Path("scripts/smoke_exe.ps1").read_text(encoding="utf-8")

        self.assertIn("Start-Process", script)
        self.assertIn("-Wait", script)
        self.assertIn("ExitCode", script)

    def test_smoke_script_can_run_gui_and_capability_checks_together(self) -> None:
        script = Path("scripts/smoke_exe.ps1").read_text(encoding="utf-8")

        self.assertIn('ValidateSet("Gui", "Workflow", "Capabilities", "Runtime", "All")', script)
        self.assertIn('@("Gui", "Workflow", "Capabilities", "Runtime")', script)

    def test_all_mode_invokes_the_runtime_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = Path("outputs/test-smoke-runtime-calls.txt").resolve()
            calls.unlink(missing_ok=True)
            self.addCleanup(calls.unlink, missing_ok=True)
            fake = root / "fake-runner.cmd"
            fake.write_text(f'@echo %*>>"{calls}"\n@exit /b 0\n', encoding="utf-8")

            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(Path("scripts/smoke_exe.ps1").resolve()),
                    "-Executable",
                    str(fake),
                    "-Mode",
                    "All",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertIn("--pose2sim-runtime-check", calls.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
