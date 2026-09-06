import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from app.gui.main_window import MainWindow
from app.gui.pages.playback_3d_page import Playback3DPage
from app.project.manager import ProjectManager


class Playback3DPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _wait_for(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def _project(self, root: Path) -> ProjectManager:
        project = ProjectManager.create(root / "project", "三维回放")
        source = Path("tests/fixtures/real_data/pose3d/three_frames_65_markers.trc")
        target = project.root / "pose-3d" / "trial_P0_1-3.trc"
        shutil.copy2(source, target)
        return project

    def test_project_trajectory_is_registered_loaded_and_played(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            window = MainWindow()

            self.assertIn("playback_3d", window._pages)
            self.assertTrue(window.open_project(project))
            page = window._pages["playback_3d"]
            self.assertIsInstance(page, Playback3DPage)
            self.assertEqual(page.source_selector.count(), 1)
            self.assertTrue(self._wait_for(lambda: page.trajectory is not None))
            page.play()
            self.assertTrue(self._wait_for(lambda: page.frame_index > 0, timeout=1.0))
            page.stop()
            self.assertFalse(page.play_timer.isActive())
            window.close()

    def test_small_page_keeps_controls_available_through_scrollable_inspector(self) -> None:
        page = Playback3DPage()
        page.resize(620, 480)
        page.show()
        self.application.processEvents()

        self.assertTrue(page.findChildren(QScrollArea))
        self.assertGreater(page.canvas.width(), 0)
        page.close()


if __name__ == "__main__":
    unittest.main()
