import json
import sys
import tempfile
import unittest
from pathlib import Path

from app.adapters.caliscope.reader import CaliscopeReader
from app.adapters.pose2sim.runner import PipelineRunner
from app.tasks.base import TaskRequest


class AdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
