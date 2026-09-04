import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from app.analysis.comparison import ComparisonMember
from app.analysis.model import MetricTable
from app.gui.main_window import MainWindow
from app.gui.pages.comparison_page import ComparisonPage
from app.project.manager import ProjectManager


def _member(project_id: str, values: tuple[float, ...]) -> ComparisonMember:
    table = MetricTable(
        (0, 1, 2),
        (0.0, 1.0, 2.0),
        {"hip.speed": values},
        {"hip.speed": "m/s"},
        {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
        {"hip.speed": {"metric_id": "speed:hip", "input_labels": ("hip",), "input_version": project_id + "-v1"}},
    )
    return ComparisonMember(project_id, "person-1", "trial-1", table)


class ComparisonPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_comparison_page_builds_in_background_and_exports(self) -> None:
        page = ComparisonPage()
        self.assertIsInstance(page.findChild(QScrollArea, "comparison_scroll"), QScrollArea)
        self.assertIsNotNone(page.findChild(object, "comparison_build_button"))
        self.assertIsNotNone(page.findChild(object, "comparison_export_json_button"))
        self.assertIsNotNone(page.findChild(object, "comparison_table"))
        page.set_members((_member("project-a", (1.0, 2.0, 3.0)), _member("project-b", (4.0, 5.0, 6.0))))
        page.build_report()
        deadline = time.monotonic() + 2.0
        while page.comparison_table.rowCount() == 0 and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertGreater(page.comparison_table.rowCount(), 0)
        with tempfile.TemporaryDirectory() as directory:
            page.export_report(Path(directory) / "comparison.json", "json")
            self.assertTrue((Path(directory) / "comparison.json").is_file())
        page.close()

    def test_main_window_registers_comparison_page_and_project_switch_clears_report(self) -> None:
        window = MainWindow()
        self.assertIsInstance(window._pages["comparison"], ComparisonPage)
        page = window._pages["comparison"]
        page.set_members((_member("project-a", (1.0, 2.0, 3.0)), _member("project-b", (4.0, 5.0, 6.0))))
        page.build_report()
        deadline = time.monotonic() + 2.0
        while page.comparison_table.rowCount() == 0 and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertGreater(page.comparison_table.rowCount(), 0)

        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "comparison")
            window.open_project(project)
        self.assertEqual(page.comparison_table.rowCount(), 0)
        window.close()


if __name__ == "__main__":
    unittest.main()
