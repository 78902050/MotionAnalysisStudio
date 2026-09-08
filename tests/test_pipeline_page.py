import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget

from app.adapters.pose2sim.runner import RunResult
from app.gui.pages.pipeline_page import PipelinePage
from app.pipeline.dependency_graph import GENERAL_POSE2SIM_STAGES
from app.project.manager import ProjectManager
from app.tasks.base import TaskResult


class _TaskHandle:
    task_id = "task-page"
    project_id = "project-page"
    generation = 1
    name = "pose2sim-pipeline"

    def __init__(self, result: TaskResult) -> None:
        self.result = result
        self.cancelled = False

    def wait(self, timeout=None):
        del timeout
        return self.result

    def cancel(self):
        self.cancelled = True


class _Launcher:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.calls = []
        self.handle = None

    def start(self, project, stages):
        selected = tuple(stages)
        self.calls.append((project, selected))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("stage started\nstage completed\n", encoding="utf-8")
        run_result = RunResult(
            "pipeline-page",
            str(project.manifest["project_id"]),
            1,
            selected,
            True,
            False,
            self.log_path,
        )
        self.handle = _TaskHandle(
            TaskResult(
                "task-page",
                str(project.manifest["project_id"]),
                1,
                "pose2sim-pipeline",
                "succeeded",
                value=run_result,
            )
        )
        return self.handle

    def log_path_for(self, task_id):
        return self.log_path if task_id == "task-page" else None


class PipelinePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_stage_list_and_run_actions_follow_config_validity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "流程界面")
            launcher = _Launcher(project.root / "logs" / "ui.log")
            page = PipelinePage(launcher=launcher)
            page.set_project(project)

            self.assertEqual(page.stage_list.count(), 8)
            self.assertFalse(page.run_current_button.isEnabled())
            self.assertFalse(page.run_selected_button.isEnabled())
            self.assertFalse(page.run_from_button.isEnabled())

            page.config_editor.setPlainText("# config\n[project]\nname = \"trial\"\n")
            self.assertTrue(page.save())
            self.assertTrue(page.run_current_button.isEnabled())
            self.assertIn("有效", page.config_status.text())
            self.assertTrue((project.root / "config" / "backups").is_dir())
            page.close()

    def test_run_current_tails_log_and_view_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "实时日志")
            project.path_for("config").write_text(
                "[project]\nname = \"trial\"\n", encoding="utf-8"
            )
            launcher = _Launcher(project.root / "logs" / "ui.log")
            page = PipelinePage(launcher=launcher)
            page.set_project(project)
            page.stage_list.setCurrentRow(2)

            self.assertTrue(page.run_current())
            page._poll_run()

            self.assertEqual(launcher.calls[0][1], ("poseEstimation",))
            self.assertIn("stage completed", page.log_viewer.toPlainText())
            page._append_log("\n".join(f"line-{index}" for index in range(6000)))
            self.assertLessEqual(page.log_viewer.document().blockCount(), 5000)
            self.assertIn("已完成", page.run_status.text())
            page.close()

    def test_resizable_page_keeps_controls_scrollable_at_small_size(self) -> None:
        page = PipelinePage(settings=QSettings())
        page.resize(620, 480)
        page.show()
        self.application.processEvents()

        self.assertTrue(page.findChildren(QSplitter))
        areas = page.findChildren(QScrollArea)
        self.assertTrue(areas)
        self.assertTrue(
            any(area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded for area in areas)
        )
        self.assertIsInstance(page.config_editor, QPlainTextEdit)
        self.assertTrue(page.log_viewer.isReadOnly())
        page.close()

    def test_project_switch_clears_finished_or_cancelled_page_handle_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = ProjectManager.create(root / "first", "first")
            second = ProjectManager.create(root / "second", "second")
            second.path_for("config").write_text("[project]\nname = \"second\"\n", encoding="utf-8")
            launcher = _Launcher(root / "run.log")
            page = PipelinePage(launcher=launcher)
            page.set_project(first)
            page._handle = _TaskHandle(TaskResult("old", "old", 0, "old", "cancelled"))

            page.set_project(second)

            self.assertIsNone(page._handle)
            self.assertTrue(page.run_current_button.isEnabled())
            page.close()

    def test_import_config_file_updates_project_copy_and_parameter_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "config import")
            source = root / "外部" / "Config.toml"
            source.parent.mkdir()
            source.write_text("[project]\nframe_rate = 60\n[pose]\ndet_frequency = 2\n", encoding="utf-8")
            source_before = source.read_bytes()
            page = PipelinePage()
            page.set_project(project)

            with patch(
                "app.gui.pages.pipeline_page.QFileDialog.getOpenFileName",
                return_value=(str(source), "Config.toml"),
            ):
                page.import_config_button.click()

            self.assertEqual(source.read_bytes(), source_before)
            self.assertIn("det_frequency = 2", project.path_for("config").read_text(encoding="utf-8"))
            self.assertIsNotNone(page.parameter_editor.item_for(("pose", "det_frequency")))
            self.assertTrue(page.findChildren(QTabWidget))
            self.assertIsNotNone(page.findChild(QPushButton, "pipeline_import_config"))
            page.close()


if __name__ == "__main__":
    unittest.main()
