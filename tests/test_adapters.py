import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.adapters.caliscope.reader import CaliscopeReader
from app.adapters.pose2sim.runner import PipelineRunner
from app.tasks.base import TaskRequest


class AdapterTests(unittest.TestCase):
    @staticmethod
    def _process_exists(process_id: int) -> bool:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"if (Get-Process -Id {process_id} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
            ],
            capture_output=True,
            check=False,
        )
        return completed.returncode == 0

    def test_pose2sim_runner_uses_allowlist_and_persists_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = PipelineRunner(
                commands={
                    "synchronization": [
                        sys.executable,
                        "-c",
                        "import sys; print('out'); print('err', file=sys.stderr)",
                    ]
                },
                allowed_stages=("synchronization",),
                log_dir=root / "logs",
            )
            result = runner.run(
                TaskRequest("project-a", 2, "sync", {}), ("synchronization",)
            )

            self.assertTrue(result.succeeded)
            self.assertEqual(result.project_id, "project-a")
            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("out", log_text)
            self.assertIn("err", log_text)
            with self.assertRaises(ValueError):
                runner.run(TaskRequest("project-a", 2, "pose", {}), ("poseEstimation",))

    def test_caliscope_reader_only_reads_json_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "标定.json"
            source.write_text(json.dumps({"camera": "cam01"}, ensure_ascii=False), encoding="utf-8")
            before = source.read_bytes()

            data = CaliscopeReader(source).read()

            self.assertEqual(data, {"camera": "cam01"})
            self.assertEqual(source.read_bytes(), before)

    def test_pose2sim_runner_start_returns_handle_that_can_cancel_active_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            started = Path(directory) / "started.txt"
            runner = PipelineRunner(
                commands={
                    "synchronization": [
                        sys.executable,
                        "-c",
                        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('started'); time.sleep(30)",
                        str(started),
                    ]
                },
                allowed_stages=("synchronization",),
                log_dir=Path(directory) / "logs",
            )
            self.assertTrue(
                hasattr(runner, "start"),
                "PipelineRunner.start must expose a task handle before execution completes",
            )

            before = time.monotonic()
            handle = runner.start(
                TaskRequest("project-a", 2, "sync", {}), ("synchronization",)
            )
            self.assertLess(time.monotonic() - before, 0.25)
            self.assertEqual(handle.project_id, "project-a")
            deadline = time.monotonic() + 2
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists(), "test subprocess did not start")
            handle.cancel()
            result = handle.wait(5)

            self.assertTrue(result.cancelled)
            self.assertFalse(result.succeeded)

    def test_pose2sim_runner_cancel_terminates_spawned_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            child_pid_path = Path(directory) / "child-pid.txt"
            parent_code = (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
            )
            runner = PipelineRunner(
                commands={
                    "synchronization": [sys.executable, "-c", parent_code, str(child_pid_path)]
                },
                allowed_stages=("synchronization",),
                log_dir=Path(directory) / "logs",
            )
            handle = runner.start(
                TaskRequest("project-a", 2, "sync", {}), ("synchronization",)
            )
            deadline = time.monotonic() + 2
            while not child_pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(child_pid_path.exists(), "child process did not start")
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            try:
                handle.cancel()
                result = handle.wait(5)
                self.assertTrue(result.cancelled)
                deadline = time.monotonic() + 3
                while self._process_exists(child_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(
                    self._process_exists(child_pid),
                    f"spawned child process {child_pid} survived cancellation",
                )
            finally:
                if self._process_exists(child_pid):
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(child_pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )


if __name__ == "__main__":
    unittest.main()
