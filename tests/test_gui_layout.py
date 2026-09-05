import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from app.gui.main_window import MainWindow
from app.gui.pages.media_page import MediaPage
from app.gui.pages.settings_page import SettingsPage
from app.analysis.comparison import ComparisonMember, ComparisonRequest, ComparisonService
from app.analysis.model import MetricTable
from app.gui.pages.comparison_page import ComparisonPage


class GuiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_real_media_and_settings_pages_are_registered_and_scrollable(self) -> None:
        window = MainWindow()

        self.assertIsInstance(window._pages["media"], MediaPage)
        self.assertIsInstance(window._pages["settings"], SettingsPage)
        self.assertTrue(window._pages["media"].findChildren(QScrollArea))
        self.assertTrue(window._pages["settings"].findChildren(QScrollArea))
        window.close()

    def test_collapsed_navigation_keeps_icons_and_tooltips(self) -> None:
        window = MainWindow()
        window.show()
        self.application.processEvents()
        window._apply_navigation_collapsed(False)

        window.toggle_navigation()

        for index in range(window.navigation_list.count()):
            item = window.navigation_list.item(index)
            self.assertFalse(item.icon().isNull())
            self.assertTrue(item.toolTip())
            self.assertEqual(item.text(), "")
        window.close()

    def test_small_window_pages_remain_accessible_through_scrollbars(self) -> None:
        window = MainWindow()
        window.resize(620, 480)
        window.show()
        for page_id in ("media", "settings", "calibration", "association", "analysis"):
            self.assertTrue(window.navigate(page_id))
            self.application.processEvents()
            areas = window.current_page.findChildren(QScrollArea)
            self.assertTrue(areas)
            self.assertTrue(
                any(
                    area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    for area in areas
                )
            )
        window.close()

    def test_large_comparison_table_is_filled_without_long_event_loop_stalls(self) -> None:
        count = 6000
        table = MetricTable(
            tuple(range(count)),
            tuple(float(index) for index in range(count)),
            {"hip.speed": tuple(float(index) for index in range(count))},
            {"hip.speed": "m/s"},
            {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
            {"hip.speed": {"metric_id": "speed:hip", "input_version": "large-v1"}},
        )
        member = ComparisonMember("large", "person", "trial", table)
        report = ComparisonService((member,)).build(
            ComparisonRequest(("large",), ("person",), ("trial",), "frame")
        )
        page = ComparisonPage()
        heartbeat_times: list[float] = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: heartbeat_times.append(time.monotonic()))
        heartbeat.start()

        started = time.monotonic()
        page._fill_table(report)
        while page.comparison_table.rowCount() < len(report.rows) and time.monotonic() - started < 5.0:
            self.application.processEvents()
            time.sleep(0.001)
        heartbeat.stop()

        gaps = [current - previous for previous, current in zip(heartbeat_times, heartbeat_times[1:])]
        self.assertEqual(page.comparison_table.rowCount(), len(report.rows))
        self.assertGreater(len(heartbeat_times), 2)
        self.assertLess(max(gaps, default=0.0), 0.25)
        page.close()


if __name__ == "__main__":
    unittest.main()
