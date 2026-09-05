import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

from app.analysis.model import MetricTable
from app.gui.main_window import MainWindow
from app.gui.pages.events_page import EventsPage
from app.project.manager import ProjectManager


class EventsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _metrics() -> MetricTable:
        values = (0.0, 1.0, 2.0, 0.0)
        return MetricTable(
            (0, 1, 2, 3),
            (0.0, 1.0, 2.0, 3.0),
            {"hip.speed": values},
            {"hip.speed": "m/s"},
            {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
            {"hip.speed": {"metric_id": "speed:hip", "input_labels": ("hip",)}},
        )

    def test_events_page_is_scrollable_and_detects_events_in_background(self) -> None:
        page = EventsPage()
        self.assertIsInstance(page.findChild(QScrollArea, "events_scroll"), QScrollArea)
        self.assertIsNotNone(page.findChild(object, "events_detect_button"))
        self.assertIsNotNone(page.findChild(object, "events_table"))
        self.assertIsNotNone(page.findChild(object, "events_cycle_table"))

        page.set_metric_table(self._metrics())
        unit = page.findChild(QLabel, "events_metric_unit")
        self.assertIsNotNone(unit)
        self.assertEqual(unit.text(), "m/s")
        page.detect()
        deadline = time.monotonic() + 2.0
        while page.events_table.rowCount() == 0 and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertEqual(page.events_table.rowCount(), 1)
        page.close()

    def test_main_window_registers_events_page_and_project_switch_clears_results(self) -> None:
        window = MainWindow()
        self.assertIsInstance(window._pages["events"], EventsPage)
        page = window._pages["events"]
        page.set_metric_table(self._metrics())
        page.detect()
        deadline = time.monotonic() + 2.0
        while page.events_table.rowCount() == 0 and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertEqual(page.events_table.rowCount(), 1)

        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "events")
            window.open_project(project)
        self.assertEqual(page.events_table.rowCount(), 0)
        window.close()


if __name__ == "__main__":
    unittest.main()
