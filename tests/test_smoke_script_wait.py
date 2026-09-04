import unittest
from pathlib import Path


class SmokeScriptWaitTests(unittest.TestCase):
    def test_smoke_script_waits_for_windowed_executable_and_checks_exit_code(self) -> None:
        script = Path("scripts/smoke_exe.ps1").read_text(encoding="utf-8")

        self.assertIn("Start-Process", script)
        self.assertIn("-Wait", script)
        self.assertIn("ExitCode", script)


if __name__ == "__main__":
    unittest.main()
