import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.gui.main_window import MainWindow
from app.gui.pages.playback_3d_page import Playback3DPage
from app.gui.pages.quality_3d_page import Quality3DPage
from app.quality.model import QualityReport


def _report() -> QualityReport:
    issue = QualityIssue(
        issue_id="issue-3d-1",
        kind="missing_3d_point",
        severity="warning",
        target=FrameAddress("cam01", "pose3d", 286),
        person=PersonAddress("P1", None, 1),
        keypoint=KeypointAddress("HALPE_26", "LWrist", 9),
        message="三维点缺失",
        evidence={},
    )
    return QualityReport.create("report-jump", {}, (issue,), {})


class Quality3DPlaybackJumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_quality_issue_opens_matching_person_and_frame_in_player(self) -> None:
        window = MainWindow()
        quality = window._pages["quality_3d"]
        player = window._pages["playback_3d"]
        self.assertIsInstance(quality, Quality3DPage)
        self.assertIsInstance(player, Playback3DPage)
        quality.set_report(_report(), {})
        quality.select_issue("issue-3d-1")

        quality.open_in_playback()

        self.assertIs(window.current_page, player)
        self.assertEqual(player.pending_target, ("P1", 286))
        window.close()

    def test_playback_button_is_disabled_without_selected_issue(self) -> None:
        page = Quality3DPage()
        page.set_report(_report(), {})
        self.assertFalse(page.playback_button.isEnabled())
        page.close()


if __name__ == "__main__":
    unittest.main()
