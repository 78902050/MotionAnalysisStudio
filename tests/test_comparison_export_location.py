import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.analysis.comparison import ComparisonMember
from app.analysis.model import MetricTable
from app.gui.pages.comparison_page import ComparisonPage
from app.project.manager import ProjectManager


def _member() -> ComparisonMember:
    table = MetricTable(
        (0, 1),
        (0.0, 1.0),
        {"hip.speed": (1.0, 2.0)},
        {"hip.speed": "m/s"},
        {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
        {"hip.speed": {"metric_id": "speed:hip", "input_labels": ("hip",), "input_version": "v1"}},
    )
    return ComparisonMember("project-a", "person-1", "trial-1", table)


class ComparisonExportLocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_default_export_stays_inside_project_comparisons_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "comparison")
            page = ComparisonPage()
            page.set_project(project)
            page.set_members((_member(),))
            page.build_report()
            deadline = time.monotonic() + 2.0
            while page.report is None and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(page.report)
            assert page.report is not None
            default_path = Path.cwd() / f"{page.report.report_id}.json"
            existed_before = default_path.exists()
            try:
                page._choose_export("json")
                expected = project.root / "reports" / "comparisons" / default_path.name
                self.assertTrue(expected.is_file())
            finally:
                if not existed_before and default_path.exists():
                    default_path.unlink()
            page.close()


if __name__ == "__main__":
    unittest.main()
