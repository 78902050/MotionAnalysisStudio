import math
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.gui.widgets.trajectory_canvas import TrajectoryCanvas
from app.playback.model import PlaybackTrajectory, TrajectorySource


class TrajectoryCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _trajectory(self) -> PlaybackTrajectory:
        missing = (math.nan, math.nan, math.nan)
        return PlaybackTrajectory(
            (1, 2, 3, 4),
            (0.0, 0.1, 0.2, 0.3),
            {
                "Hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), missing, (3.0, 0.0, 0.0)),
                "Neck": ((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), missing, (3.0, 0.0, 1.0)),
            },
            "m",
            TrajectorySource(Path("trial_P0_1-4.trc"), "trc", "trial", "P0", "raw"),
        )

    def test_trail_does_not_connect_across_nan_gap(self) -> None:
        canvas = TrajectoryCanvas()
        canvas.set_trajectory(self._trajectory(), (("Hip", "Neck"),))
        canvas.set_frame_index(3)

        self.assertEqual(canvas.visible_trail_segment_count("Hip"), 1)
        self.assertEqual(canvas.frame_index, 3)

    def test_fit_all_and_offscreen_render_succeed(self) -> None:
        canvas = TrajectoryCanvas()
        canvas.resize(400, 300)
        canvas.set_trajectory(self._trajectory(), (("Hip", "Neck"),))
        canvas.fit_all()
        image = QImage(400, 300, QImage.Format.Format_ARGB32)
        canvas.render(image)

        self.assertGreater(canvas.view_transform.zoom, 0)
        self.assertFalse(image.isNull())

    def test_fit_all_uses_current_pose_not_whole_trial_translation(self) -> None:
        trajectory = PlaybackTrajectory(
            (1, 2),
            (0.0, 0.1),
            {
                "Hip": ((0.0, 0.0, 0.0), (1000.0, 0.0, 0.0)),
                "Head": ((1.0, 0.0, 1.0), (1001.0, 0.0, 1.0)),
            },
            "m",
            TrajectorySource(Path("trial_P0_1-2.trc"), "trc", "trial", "P0", "raw"),
        )
        canvas = TrajectoryCanvas()
        canvas.resize(400, 300)
        canvas.set_trajectory(trajectory, (("Hip", "Head"),))

        self.assertGreater(canvas.view_transform.zoom, 200)


if __name__ == "__main__":
    unittest.main()
