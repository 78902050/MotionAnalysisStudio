import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.application.controller import ApplicationController
from app.gui.pages.media_page import MediaPage
from app.gui.pages.settings_page import SettingsPage
from app.gui.pages.comparison_page import ComparisonPage
from app.analysis.comparison import ComparisonMember, ComparisonRequest, ComparisonService
from app.analysis.model import MetricTable
from app.project.manager import ProjectManager


class _Capture:
    def __init__(self, path: str) -> None:
        self.path = path

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        values = {5: 60.0, 7: 600.0, 3: 1920.0, 4: 1080.0}
        return values.get(prop, 0.0)

    def release(self) -> None:
        pass


class GuiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_media_page_scans_camera_metadata_once_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "媒体项目")
            video = project.root / "videos" / "cam01.mp4"
            video.parent.mkdir()
            video.write_bytes(b"fixture")
            project.manifest["cameras"] = [
                {"camera_id": "cam01", "video_path": "videos/cam01.mp4"},
                {"camera_id": "cam02", "video_path": "videos/missing.mp4"},
            ]
            project.save_manifest()
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            page = MediaPage(controller=controller)

            with patch("app.gui.pages.media_page.cv2.VideoCapture", _Capture):
                page.set_project(project)
                for _ in range(100):
                    self.application.processEvents()
                    if page.model.rowCount() == 2:
                        break
                    QTest.qWait(10)
                first_scan_count = page.scan_count
                page.set_project(project)

            self.assertEqual(page.model.rowCount(), 2)
            self.assertEqual(page.model.records[0].resolution, "1920 × 1080")
            self.assertEqual(page.model.records[0].duration_seconds, 10.0)
            self.assertIn("不存在", page.model.records[1].issue)
            self.assertEqual(page.scan_count, first_scan_count)
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()

    def test_settings_rejects_missing_tool_path_and_persists_valid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            page = SettingsPage(settings=settings)
            page.pose2sim_path.setText(str(root / "missing.exe"))

            self.assertFalse(page.save_settings())
            self.assertFalse(settings.contains("tools/pose2sim_path"))

            tool = root / "python.exe"
            tool.write_bytes(b"")
            page.pose2sim_path.setText(str(tool))
            page.caliscope_path.setText("")
            page.cache_capacity.setValue(48)
            page.nudge_step.setValue(2.5)

            self.assertTrue(page.save_settings())
            self.assertEqual(settings.value("tools/pose2sim_path"), str(tool))
            self.assertEqual(settings.value("media/cache_capacity", type=int), 48)
            self.assertEqual(settings.value("correction/nudge_step", type=float), 2.5)
            page.close()

    def test_project_report_export_uses_task_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "导出项目")
            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            table = MetricTable(
                (0, 1),
                (0.0, 1.0),
                {"hip.speed": (1.0, 2.0)},
                {"hip.speed": "m/s"},
                {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
                {"hip.speed": {"metric_id": "speed:hip", "input_version": "v1"}},
            )
            member = ComparisonMember("project", "person", "trial", table)
            report = ComparisonService((member,)).build(
                ComparisonRequest(("project",), ("person",), ("trial",), "frame")
            )
            page = ComparisonPage(project, controller=controller)
            page.report = report
            destination = project.root / "reports" / "comparisons" / "task.json"

            page.export_report(destination, "json")
            for _ in range(100):
                self.application.processEvents()
                if page._export_handle is None:
                    break
                QTest.qWait(10)

            self.assertTrue(destination.is_file())
            self.assertTrue(any(item.name == "comparison-export" for item in controller.supervisor.snapshots()))
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            page.close()


if __name__ == "__main__":
    unittest.main()
