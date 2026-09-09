import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, QSettings, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QScrollArea, QSplitter

from app.domain.addresses import FrameAddress
from app.gui.pages.correction_page import CorrectionPage


class _ManualFrameProvider(QObject):
    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)

    def request(self, _address: object) -> None:
        pass


class CorrectionPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_dense_correction_workspace_uses_adjustable_splitters_and_scrollable_details(self) -> None:
        page = CorrectionPage()
        page.resize(1120, 720)
        page.show()
        self.application.processEvents()

        workspace = page.findChild(QSplitter, "correction_workspace_splitter")
        views = page.findChild(QSplitter, "correction_views_splitter")
        details = page.findChild(QScrollArea, "correction_details_scroll")

        self.assertIsNotNone(workspace)
        self.assertIsNotNone(views)
        self.assertIsNotNone(details)
        self.assertEqual(details.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for object_name in (
            "correction_previous_button",
            "correction_next_button",
            "correction_undo_button",
            "correction_redo_button",
            "correction_reset_button",
            "correction_save_button",
            "correction_save_rerun_button",
        ):
            self.assertIsNotNone(page.findChild(object, object_name))
        page.close()

    def test_narrow_window_keeps_action_bar_and_allows_details_to_scroll(self) -> None:
        page = CorrectionPage()
        page.resize(620, 480)
        page.show()
        self.application.processEvents()

        details = page.findChild(QScrollArea, "correction_details_scroll")
        self.assertIsNotNone(details)
        assert details is not None
        self.assertTrue(details.widget().minimumHeight() >= 480)
        self.assertTrue(page.findChild(object, "correction_action_bar").isVisible())
        page.close()

    def test_tool_panels_scroll_and_user_layout_is_restored(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                f"{directory}/layout.ini",
                QSettings.Format.IniFormat,
            )
            page = CorrectionPage(settings=settings)
            page.resize(1120, 720)
            page.show()
            self.application.processEvents()

            issue_scroll = page.findChild(QScrollArea, "correction_issue_scroll")
            action_scroll = page.findChild(QScrollArea, "correction_action_scroll")
            self.assertIsNotNone(issue_scroll)
            self.assertIsNotNone(action_scroll)
            assert issue_scroll is not None and action_scroll is not None
            self.assertEqual(
                issue_scroll.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            self.assertEqual(
                action_scroll.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            page.view_count.setCurrentIndex(page.view_count.findData(4))
            page.workspace_splitter.setSizes([180, 650, 290])
            page.views_splitter.setSizes([300, 200, 100, 100])
            expected_workspace = page.workspace_splitter.sizes()
            expected_views = page.views_splitter.sizes()
            page.persist_layout()
            page.close()

            restored = CorrectionPage(settings=settings)
            self.assertEqual(restored.view_count.currentData(), 4)
            self.assertEqual(settings.value("correction/workspace_sizes"), expected_workspace)
            self.assertEqual(settings.value("correction/view_sizes"), expected_views)
            restored.close()

    def test_selected_camera_becomes_the_first_visible_view(self) -> None:
        page = CorrectionPage()
        page.set_cameras(["cam01", "cam02", "cam03"])
        page.set_view_count(1)

        page.camera_selector.setCurrentText("cam03")
        self.application.processEvents()

        self.assertEqual(page._view_cards[0].property("camera"), "cam03")
        self.assertEqual(page.settings.value("correction/selected_camera"), "cam03")
        page.close()

    def test_four_camera_mode_uses_two_rows_and_keeps_every_view_visible(self) -> None:
        page = CorrectionPage()
        page.resize(1120, 720)
        page.set_cameras(["cam01", "cam02", "cam03", "cam04"])
        page.camera_selector.setCurrentText("cam01")
        page.set_view_count(4)
        page.show()
        self.application.processEvents()

        self.assertTrue(all(card.isVisible() for card in page._view_cards))
        self.assertEqual(
            [card.property("camera") for card in page._view_cards],
            ["cam01", "cam02", "cam03", "cam04"],
        )
        self.assertLess(
            page._view_cards[0].mapTo(page, QPoint()).y(),
            page._view_cards[2].mapTo(page, QPoint()).y(),
        )
        self.assertLess(
            page._view_cards[1].mapTo(page, QPoint()).y(),
            page._view_cards[3].mapTo(page, QPoint()).y(),
        )
        page.close()

    def test_dragging_a_camera_row_splitter_persists_custom_view_sizes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                f"{directory}/layout.ini",
                QSettings.Format.IniFormat,
            )
            page = CorrectionPage(settings=settings)
            page.resize(1120, 720)
            page.set_view_count(4)
            page.show()
            self.application.processEvents()

            row = page._view_row_splitters[0]
            row.setSizes([320, 180])
            row.splitterMoved.emit(320, 1)
            settings.sync()

            self.assertEqual(
                settings.value("correction/view_top_sizes"),
                row.sizes(),
            )
            page.close()

    def test_frame_buttons_and_timeline_emit_synchronized_frame_requests(self) -> None:
        page = CorrectionPage()
        requested: list[int] = []
        page.frame_requested.connect(requested.append)
        page.set_timeline_range(5, 20)
        page.timeline.setValue(10)

        page.previous_frame_button.click()
        page.next_frame_button.click()
        page.timeline.setValue(17)
        page.timeline.sliderReleased.emit()

        self.assertEqual(requested, [9, 11, 17])
        page.close()

    def test_playback_advances_available_pose_frames_and_stops_at_the_end(self) -> None:
        page = CorrectionPage()
        page.set_pose_inventory({"cam01": [4, 7, 10]})
        requested: list[tuple[str, int, int, int]] = []
        page.browse_requested.connect(
            lambda camera, frame, person, keypoint: requested.append(
                (camera, frame, person, keypoint)
            )
        )

        page.play_button.click()
        self.assertTrue(page._play_timer.isActive())
        page._play_next_frame()
        self.assertEqual(page.timeline.value(), 7)
        self.assertEqual(requested, [("cam01", 7, 0, 0)])
        page._play_next_frame()
        self.assertEqual(page.timeline.value(), 10)
        page._play_next_frame()

        self.assertFalse(page._play_timer.isActive())
        self.assertEqual(page.play_button.text(), "播放")
        page.close()

    def test_playback_waits_for_current_video_frame_before_advancing_skeleton(self) -> None:
        page = CorrectionPage(provider=_ManualFrameProvider())
        page.set_pose_inventory({"cam01": [4, 7, 10]})
        page.play_button.click()
        page._play_next_frame()
        page.set_view_addresses({"cam01": FrameAddress("cam01", "raw", 7)})

        page._play_next_frame()
        self.assertEqual(page.timeline.value(), 7)
        page._on_frame_ready("cam01", 7, QImage(8, 8, QImage.Format.Format_RGB32))
        page._play_next_frame()

        self.assertEqual(page.timeline.value(), 10)
        page.close()

    def test_empty_project_clears_camera_bindings_from_previous_project(self) -> None:
        page = CorrectionPage()
        page.set_cameras(["cam01", "cam02"])

        page.set_cameras([])

        self.assertEqual(page.camera_selector.currentText(), "请先打开项目")
        self.assertTrue(all(not card.property("camera") for card in page._view_cards))
        page.close()


if __name__ == "__main__":
    unittest.main()
