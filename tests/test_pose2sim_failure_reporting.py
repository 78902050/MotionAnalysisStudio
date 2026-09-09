import tempfile
import unittest
from pathlib import Path

from app.adapters.pose2sim.runner import RunResult, StageRunResult
from app.application.controller import ApplicationController
from app.application.pipeline_launcher import PipelineLauncher
from app.project.manager import ProjectManager


class _ImmediateHandle:
    def __init__(self, result: RunResult) -> None:
        self.result = result

    def wait(self, timeout=None) -> RunResult:
        del timeout
        return self.result

    def cancel(self) -> None:
        return None


class _FailedRunner:
    log_text = ""

    def __init__(self, _commands, _allowed_stages, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)

    def start(self, request, stages) -> _ImmediateHandle:
        log_path = self.log_dir / request.payload["log_file"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(self.log_text, encoding="utf-8")
        now = "2026-09-09T00:00:00+00:00"
        result = RunResult(
            "failed-run",
            request.project_id,
            request.generation,
            tuple(stages),
            False,
            False,
            log_path,
            "stage poseEstimation exited with code 1",
            "poseEstimation",
            (StageRunResult("poseEstimation", "failed", now, now, 0.1, 1),),
        )
        return _ImmediateHandle(result)


class Pose2SimFailureReportingTests(unittest.TestCase):
    def _run_failure(self, log_text: str):
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "失败归因")
            project.path_for("config").write_text(
                "[project]\nname = 'failure'\n", encoding="utf-8"
            )
            videos = project.root / "videos"
            videos.mkdir(exist_ok=True)
            (videos / "cam01.mp4").write_bytes(b"video")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            runner_type = type("ConfiguredFailedRunner", (_FailedRunner,), {"log_text": log_text})
            launcher = PipelineLauncher(controller, runner_factory=runner_type)

            handle = launcher.start(project, ("poseEstimation",))
            result = handle.wait(3)

            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.error)
            return result.error, dict(project.manifest["last_pipeline_run"])

    def test_missing_onnx_log_produces_actionable_task_error(self) -> None:
        error, manifest_run = self._run_failure(
            "Available frontends: jax pytorch\n"
            "Exception while reading yolox_m.onnx\n"
        )

        self.assertIn("缺少 OpenVINO ONNX 前端", error)
        self.assertIn("pose2sim-", error)
        self.assertIn("缺少 OpenVINO ONNX 前端", str(manifest_run["error"]))

    def test_unknown_log_retains_stage_and_exit_code(self) -> None:
        error, manifest_run = self._run_failure("unrecognized failure\n")

        self.assertIn("poseEstimation", error)
        self.assertIn("code 1", error)
        self.assertIn("code 1", str(manifest_run["error"]))


if __name__ == "__main__":
    unittest.main()
