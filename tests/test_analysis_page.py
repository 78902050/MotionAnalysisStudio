import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.analysis.model import Trajectory
from app.gui.main_window import MainWindow
from app.gui.pages.analysis_page import AnalysisPage


class AnalysisPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _trajectory() -> Trajectory:
        return Trajectory(
            frames=(0, 1, 2),
            times=(0.0, 1.0, 2.0),
            points={"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (4.0, 0.0, 0.0))},
            coordinate_unit="m",
            coordinate_system="world",
            source_path="fixture.trc",
            source_version="fixture-v1",
        )

    def test_main_window_registers_analysis_page(self) -> None:
        window = MainWindow()

        self.assertIsInstance(window._pages["analysis"], AnalysisPage)
        self.assertIsNotNone(window._pages["analysis"].findChild(object, "analysis_metric_table"))

        window.close()

    def test_metric_calculation_runs_in_background_and_updates_table(self) -> None:
        page = AnalysisPage()
        page.set_trajectory(self._trajectory())
        page.calculate()
        deadline = time.monotonic() + 2.0
        while page.metric_table.rowCount() == 0 and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)

        self.assertGreater(page.metric_table.rowCount(), 0)
        self.assertIn("hip.speed", [page.metric_table.item(row, 0).text() for row in range(page.metric_table.rowCount())])
        page.close()


if __name__ == "__main__":
    unittest.main()
