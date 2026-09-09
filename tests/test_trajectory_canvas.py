import math
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.gui.widgets.trajectory_canvas import TrajectoryCanvas
from app.gui.theme import UiPreferences, apply_theme, palette_for_name
from app.playback.model import PlaybackTrajectory, TrajectorySource
from app.playback.projection import ViewTransform, project_points


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

    def test_canvas_background_follows_application_theme(self) -> None:
        canvas = TrajectoryCanvas()
        canvas.resize(80, 60)
        image = QImage(80, 60, QImage.Format.Format_ARGB32)

        apply_theme(self.application, UiPreferences("light", 12))
        canvas.render(image)
        self.assertEqual(image.pixelColor(2, 2).name(), palette_for_name("light").canvas.casefold())

        apply_theme(self.application, UiPreferences("dark", 12))
        canvas.render(image)
        self.assertEqual(image.pixelColor(2, 2).name(), palette_for_name("dark").canvas.casefold())
        apply_theme(self.application, UiPreferences("light", 12))

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

    def test_fit_all_bounds_zoom_for_single_visible_marker(self) -> None:
        trajectory = PlaybackTrajectory(
            (1,),
            (0.0,),
            {"Marker": ((12.0, 34.0, 56.0),)},
            "mm",
            TrajectorySource(Path("trial_P0_1-1.c3d"), "c3d", "trial", "P0", "raw"),
        )
        canvas = TrajectoryCanvas()
        canvas.resize(400, 300)

        canvas.set_trajectory(trajectory)

        self.assertLessEqual(canvas.view_transform.zoom, 1e6)
        self.assertLessEqual(abs(canvas.view_transform.pan_x), 100 * canvas.view_transform.zoom)
        self.assertLessEqual(abs(canvas.view_transform.pan_y), 100 * canvas.view_transform.zoom)

    def test_direction_rotation_uses_bounded_incremental_angles(self) -> None:
        canvas = TrajectoryCanvas()
        rotate = getattr(canvas, "rotate_by", None)
        self.assertIsNotNone(rotate)

        rotate(yaw_delta=math.pi / 12, pitch_delta=math.pi / 12)

        self.assertAlmostEqual(canvas.view_transform.yaw, -0.35 + math.pi / 12)
        self.assertAlmostEqual(canvas.view_transform.pitch, -0.20 + math.pi / 12)
        rotate(pitch_delta=math.pi)
        self.assertLessEqual(canvas.view_transform.pitch, math.pi / 2)

    def test_direction_rotation_keeps_current_pose_screen_center_stable(self) -> None:
        trajectory = PlaybackTrajectory(
            (1,),
            (0.0,),
            {
                "Hip": ((1000.0, 300.0, 0.0),),
                "Head": ((1000.0, 300.0, 100.0),),
            },
            "mm",
            TrajectorySource(Path("turn_P0_1-1.trc"), "trc", "turn", "P0", "raw"),
        )
        canvas = TrajectoryCanvas()
        canvas.resize(400, 300)
        canvas.set_trajectory(trajectory, (("Hip", "Head"),))
        before_points = project_points(
            {
                "Hip": trajectory.points["Hip"][0],
                "Head": trajectory.points["Head"][0],
            },
            canvas.view_transform,
            (canvas.width(), canvas.height()),
        )
        before = QPointF(
            sum(point.x() for point in before_points.values() if point is not None) / 2,
            sum(point.y() for point in before_points.values() if point is not None) / 2,
        )

        canvas.rotate_by(yaw_delta=math.pi / 12)
        after_points = project_points(
            {
                "Hip": trajectory.points["Hip"][0],
                "Head": trajectory.points["Head"][0],
            },
            canvas.view_transform,
            (canvas.width(), canvas.height()),
        )
        after = QPointF(
            sum(point.x() for point in after_points.values() if point is not None) / 2,
            sum(point.y() for point in after_points.values() if point is not None) / 2,
        )
        self.assertAlmostEqual(after.x(), before.x(), places=6)
        self.assertAlmostEqual(after.y(), before.y(), places=6)

    def test_ghost_skeleton_uses_each_frames_world_position(self) -> None:
        trajectory = PlaybackTrajectory(
            (1, 2, 3),
            (0.0, 0.1, 0.2),
            {
                "Hip": ((-50.0, 0.0, 7.0), (0.0, 0.0, 7.0), (50.0, 0.0, 7.0)),
                "Head": ((-50.0, 0.0, 17.0), (0.0, 0.0, 17.0), (50.0, 0.0, 17.0)),
            },
            "mm",
            TrajectorySource(Path("walk_P0_1-3.trc"), "trc", "walk", "P0", "raw"),
        )
        canvas = TrajectoryCanvas()
        canvas.setMinimumSize(0, 0)
        canvas.resize(200, 100)
        canvas.set_trajectory(trajectory, (("Hip", "Head"),))
        canvas.set_frame_index(2)
        canvas.set_trail_frames(2)
        enable_ghosts = getattr(canvas, "set_ghost_poses_enabled", None)
        self.assertIsNotNone(enable_ghosts)
        enable_ghosts(True)
        canvas.view_transform = ViewTransform(yaw=0.0, pitch=0.0, zoom=1.0)
        image = QImage(200, 100, QImage.Format.Format_ARGB32)

        canvas.render(image)

        self.assertEqual(canvas.ghost_frame_indices(), (0, 1))
        background = palette_for_name("light").canvas.casefold()
        self.assertNotEqual(image.pixelColor(50, 38).name(), background)
        self.assertNotEqual(image.pixelColor(100, 38).name(), background)
        self.assertNotEqual(image.pixelColor(150, 38).name(), background)

    def test_fit_motion_window_keeps_displaced_ghosts_in_view(self) -> None:
        trajectory = PlaybackTrajectory(
            (1, 2),
            (0.0, 0.1),
            {
                "Hip": ((0.0, 0.0, 0.0), (1000.0, 0.0, 0.0)),
                "Head": ((0.0, 0.0, 100.0), (1000.0, 0.0, 100.0)),
            },
            "mm",
            TrajectorySource(Path("walk_P0_1-2.trc"), "trc", "walk", "P0", "raw"),
        )
        canvas = TrajectoryCanvas()
        canvas.resize(400, 300)
        canvas.set_trajectory(trajectory, (("Hip", "Head"),))
        canvas.set_frame_index(1)
        canvas.set_trail_frames(1)
        fit_motion = getattr(canvas, "fit_motion_window", None)
        self.assertIsNotNone(fit_motion)

        fit_motion()
        projected_start = project_points(
            {"Hip": trajectory.points["Hip"][0]},
            canvas.view_transform,
            (canvas.width(), canvas.height()),
        )["Hip"]
        projected_end = project_points(
            {"Hip": trajectory.points["Hip"][1]},
            canvas.view_transform,
            (canvas.width(), canvas.height()),
        )["Hip"]

        self.assertIsNotNone(projected_start)
        self.assertIsNotNone(projected_end)
        assert projected_start is not None and projected_end is not None
        self.assertGreaterEqual(projected_start.x(), 20)
        self.assertLessEqual(projected_end.x(), canvas.width() - 20)


if __name__ == "__main__":
    unittest.main()
