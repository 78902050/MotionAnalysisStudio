import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton

from app.application.controller import ApplicationController
from app.gui.pages.calibration_page import CalibrationPage
from app.project.manager import ProjectManager


class _Handle:
    log_path = Path("caliscope.log")

    def poll(self):
        return None

    def cancel(self):
        return None

    def wait(self, timeout=None):
        del timeout
        return 0

    def close(self):
        self.cancel()
        return True


class _Launcher:
    def __init__(self) -> None:
        self.calls = []

    def start(self, command, cwd, log_path):
        self.calls.append((command, cwd, log_path))
        return _Handle()


class CaliscopePageLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_page_launches_current_project_as_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "试次", "标定试次")
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            executable = root / "caliscope.exe"
            executable.touch()
            settings.setValue("tools/caliscope_path", str(executable))
            launcher = _Launcher()
            page = CalibrationPage(project, settings=settings, launcher=launcher)

            self.assertIsNotNone(page.findChild(QPushButton, "calibration_launch_button"))
            self.assertIsNotNone(page.findChild(QPushButton, "caliscope_convert_settings_button"))
            self.assertTrue(page.launch_caliscope())

            command, cwd, log_path = launcher.calls[0]
            self.assertEqual(command, (str(executable), "--workspace", str(project.root)))
            self.assertEqual(cwd, project.root)
            self.assertEqual(log_path.parent, project.root / "logs")
            self.assertIn("已启动", page.caliscope_status.text())
            self.assertFalse(page.launch_caliscope())
            self.assertEqual(len(launcher.calls), 1)
            self.assertIn("正在运行", page.caliscope_status.text())
            page.close()

    def test_caliscope_process_is_visible_to_task_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "试次", "任务标定")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            launcher = _Launcher()
            page = CalibrationPage(project, controller=controller, launcher=launcher)

            self.assertTrue(page.launch_caliscope())
            snapshots = controller.supervisor.snapshots()

            self.assertTrue(any(item.name == "caliscope-gui" for item in snapshots))
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()


if __name__ == "__main__":
    unittest.main()
