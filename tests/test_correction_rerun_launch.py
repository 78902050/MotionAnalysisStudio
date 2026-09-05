import sys
import tempfile
import threading
import unittest
from pathlib import Path

from app.correction.rerun import CORRECTION_RERUN_STAGES
from app.adapters.pose2sim.runner import RunResult


class CorrectionRerunLaunchTests(unittest.TestCase):
    def test_development_commands_use_application_stage_entrypoint(self) -> None:
        from app.application.correction_rerun_launcher import build_stage_commands

        config = Path("D:/项目/config/Config.toml")
        commands = build_stage_commands(
            config,
            executable=Path(sys.executable),
            frozen=False,
        )

        self.assertEqual(tuple(commands), CORRECTION_RERUN_STAGES)
        self.assertNotIn("poseEstimation", commands)
        for stage, command in commands.items():
            self.assertEqual(command[:3], (str(Path(sys.executable)), "-m", "app.main"))
            self.assertEqual(command[-4:], ("--pose2sim-stage", stage, "--pose2sim-config", str(config)))

    def test_frozen_commands_reenter_the_packaged_executable(self) -> None:
        from app.application.correction_rerun_launcher import build_stage_commands

        executable = Path("D:/dist/MotionAnalysisStudio.exe")
        commands = build_stage_commands(
            Path("D:/项目/config/Config.toml"),
            executable=executable,
            frozen=True,
        )

        for command in commands.values():
            self.assertEqual(command[0], str(executable))
            self.assertNotIn("-m", command)

    def test_main_window_registers_a_default_correction_rerun_handler(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from app.gui.main_window import MainWindow
        from app.project.manager import ProjectManager

        application = QApplication.instance() or QApplication([])
        del application
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "默认重跑")
            window = MainWindow()
            self.assertTrue(window.open_project(project, dirty_decision="discard"))
            self.assertTrue(window.controller.has_correction_rerun_handler())
            window.close()

    def test_launcher_runs_allowlisted_stages_as_a_supervised_task(self) -> None:
        from app.application.controller import ApplicationController
        from app.application.correction_rerun_launcher import CorrectionRerunLauncher
        from app.project.manager import ProjectManager

        recorded: dict[str, object] = {}

        class ImmediateHandle:
            def __init__(self, result):
                self.result = result

            def cancel(self):
                recorded["cancelled"] = True

            def wait(self, timeout=None):
                del timeout
                return self.result

        class RecordingRunner:
            def __init__(self, commands, allowed_stages, log_dir):
                recorded["commands"] = commands
                recorded["allowed_stages"] = allowed_stages
                recorded["log_dir"] = log_dir

            def start(self, request, stages):
                recorded["request"] = request
                recorded["stages"] = tuple(stages)
                return ImmediateHandle(
                    RunResult(
                        "pipeline-1",
                        request.project_id,
                        request.generation,
                        tuple(stages),
                        True,
                        False,
                        Path(request.payload["working_directory"]) / "logs" / "rerun.log",
                    )
                )

        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "受控重跑")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            handles = []
            controller.add_task_listener(handles.append)
            launcher = CorrectionRerunLauncher(controller, runner_factory=RecordingRunner)

            self.assertTrue(launcher(project, "session-1"))
            result = handles[0].wait(3)

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(recorded["stages"], CORRECTION_RERUN_STAGES)
            self.assertNotIn("poseEstimation", recorded["commands"])
            self.assertTrue(
                all(
                    project.manifest["stages"][stage]["status"] == "completed"
                    for stage in CORRECTION_RERUN_STAGES
                )
            )

    def test_supervisor_cancellation_reaches_the_pipeline_process_handle(self) -> None:
        from app.application.controller import ApplicationController
        from app.application.correction_rerun_launcher import CorrectionRerunLauncher
        from app.project.manager import ProjectManager

        pipeline_cancelled = threading.Event()

        class BlockingHandle:
            def __init__(self, request, stages):
                self.request = request
                self.stages = tuple(stages)

            def cancel(self):
                pipeline_cancelled.set()

            def wait(self, timeout=None):
                if not pipeline_cancelled.wait(timeout):
                    raise TimeoutError("still running")
                return RunResult(
                    "pipeline-cancelled",
                    self.request.project_id,
                    self.request.generation,
                    self.stages,
                    False,
                    True,
                    Path(self.request.payload["working_directory"]) / "logs" / "cancelled.log",
                    failed_stage=self.stages[0],
                )

        class BlockingRunner:
            def __init__(self, commands, allowed_stages, log_dir):
                del commands, allowed_stages, log_dir

            def start(self, request, stages):
                return BlockingHandle(request, stages)

        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "取消重跑")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            handles = []
            controller.add_task_listener(handles.append)
            launcher = CorrectionRerunLauncher(controller, runner_factory=BlockingRunner)
            self.assertTrue(launcher(project, "session-cancel"))

            self.assertTrue(controller.shutdown(dirty_decision="discard", timeout_ms=3000))

            self.assertTrue(pipeline_cancelled.is_set())
            self.assertEqual(handles[0].wait(1).status, "cancelled")
            self.assertTrue(
                all(
                    project.manifest["stages"][stage]["status"] == "pending"
                    for stage in CORRECTION_RERUN_STAGES
                )
            )


if __name__ == "__main__":
    unittest.main()
