import sys
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

from app.application.controller import ApplicationController
from app.application.pipeline_launcher import PipelineLauncher, build_pipeline_commands
from app.correction.rerun import CORRECTION_RERUN_STAGES
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.project.manager import ProjectManager
from app.tasks.base import TaskRequest
from app.adapters.pose2sim.runner import PipelineRunner, RunResult, StageRunResult
from app.main import run_pose2sim_stage


class Pose2SimPipelineTests(unittest.TestCase):
    def test_general_allowlist_has_all_eight_stages_but_correction_stays_selective(self) -> None:
        self.assertEqual(
            GENERAL_POSE2SIM_STAGES,
            (
                "calibration",
                "synchronization",
                "poseEstimation",
                "personAssociation",
                "triangulation",
                "filtering",
                "markerAugmentation",
                "kinematics",
            ),
        )
        self.assertNotIn("poseEstimation", CORRECTION_RERUN_STAGES)

    def test_pipeline_commands_reenter_stage_entrypoint_for_requested_stages(self) -> None:
        config = Path("D:/项目/config/Config.toml")

        commands = build_pipeline_commands(
            config,
            ("calibration", "poseEstimation"),
            executable=Path(sys.executable),
            frozen=False,
        )

        self.assertEqual(tuple(commands), ("calibration", "poseEstimation"))
        self.assertEqual(commands["calibration"][:3], (str(Path(sys.executable)), "-m", "app.main"))
        self.assertEqual(commands["poseEstimation"][-4:], ("--pose2sim-stage", "poseEstimation", "--pose2sim-config", str(config)))
        with self.assertRaises(ValueError):
            build_pipeline_commands(config, ("unknown",))

    def test_runner_exposes_incremental_log_and_per_stage_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = PipelineRunner(
                {
                    "calibration": (
                        sys.executable,
                        "-c",
                        "import time; print('line-1', flush=True); time.sleep(.15); print('line-2', flush=True)",
                    )
                },
                ("calibration",),
                root / "logs",
            )
            handle = runner.start(TaskRequest("project-a", 1, "pipeline", {}), ("calibration",))
            deadline = time.monotonic() + 2
            first = ""
            offset = 0
            while "line-1" not in first and time.monotonic() < deadline:
                first, offset = handle.read_log(offset)
                time.sleep(0.02)

            self.assertIn("line-1", first)
            result = handle.wait(3)
            tail, next_offset = handle.read_log(offset)

            self.assertIn("line-2", tail)
            self.assertGreater(next_offset, offset)
            self.assertTrue(result.succeeded)
            self.assertEqual(len(result.stage_results), 1)
            self.assertEqual(result.stage_results[0].stage, "calibration")
            self.assertEqual(result.stage_results[0].status, "completed")
            self.assertGreaterEqual(result.stage_results[0].duration_seconds, 0.1)

    def test_invalid_config_is_rejected_before_task_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "无效配置")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            launcher = PipelineLauncher(controller)

            with self.assertRaisesRegex(ValueError, "为空"):
                launcher.start(project, ("calibration",))

            self.assertEqual(controller.supervisor.snapshots(), ())

    def test_stage_entrypoint_dispatches_every_general_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "Config.toml"
            config.write_text("[project]\nname = \"entrypoint\"\n", encoding="utf-8")
            calls: list[str] = []
            with ExitStack() as stack:
                import Pose2Sim.Pose2Sim as pose2sim

                for stage in GENERAL_POSE2SIM_STAGES:
                    stack.enter_context(
                        patch.object(
                            pose2sim,
                            stage,
                            side_effect=lambda *args, _stage=stage, **kwargs: calls.append(_stage),
                        )
                    )
                for stage in GENERAL_POSE2SIM_STAGES:
                    self.assertEqual(run_pose2sim_stage(stage, config), 0)

            self.assertEqual(calls, list(GENERAL_POSE2SIM_STAGES))

    def test_launcher_records_completed_stage_and_log_in_manifest(self) -> None:
        class _ImmediateHandle:
            def __init__(self, result):
                self.result = result

            def wait(self, timeout=None):
                del timeout
                return self.result

            def cancel(self):
                return None

        class _Runner:
            def __init__(self, commands, allowed_stages, log_dir):
                self.log_dir = log_dir

            def start(self, request, stages):
                log_path = self.log_dir / request.payload["log_file"]
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("ok\n", encoding="utf-8")
                now = "2026-09-05T00:00:00+00:00"
                return _ImmediateHandle(
                    RunResult(
                        "run-1",
                        request.project_id,
                        request.generation,
                        tuple(stages),
                        True,
                        False,
                        log_path,
                        stage_results=(StageRunResult("filtering", "completed", now, now, 0.1, 0),),
                    )
                )

        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "流程状态")
            project.path_for("config").write_text("[project]\nname = \"trial\"\n", encoding="utf-8")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            launcher = PipelineLauncher(controller, runner_factory=_Runner)

            handle = launcher.start(project, ("filtering",))
            result = handle.wait(3)

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(project.manifest["stages"]["filtering"]["status"], "completed")
            self.assertEqual(project.manifest["last_pipeline_run"]["failed_stage"], None)
            self.assertTrue(launcher.log_path_for(handle.task_id).is_file())


if __name__ == "__main__":
    unittest.main()
