import math
import unittest

from PySide6.QtCore import QPointF

from app.playback.projection import FRONT_VIEW, SIDE_VIEW, ViewTransform, project_points


class PlaybackProjectionTests(unittest.TestCase):
    def test_front_and_side_views_project_known_axes(self) -> None:
        points = {"origin": (0.0, 0.0, 0.0), "x": (10.0, 0.0, 0.0)}

        front = project_points(points, FRONT_VIEW, (200, 100))
        side = project_points(points, SIDE_VIEW, (200, 100))

        self.assertEqual(front["origin"], QPointF(100.0, 50.0))
        self.assertGreater(front["x"].x(), 100.0)
        self.assertAlmostEqual(side["x"].x(), 100.0, places=6)

    def test_missing_point_is_not_projected_to_origin(self) -> None:
        projected = project_points(
            {"Hip": (math.nan, math.nan, math.nan)}, FRONT_VIEW, (200, 100)
        )
        self.assertIsNone(projected["Hip"])

    def test_zoom_and_pan_are_applied_in_screen_space(self) -> None:
        transform = ViewTransform(0.0, 0.0, 2.0, 5.0, -3.0, False)
        projected = project_points({"p": (4.0, 0.0, 2.0)}, transform, (100, 100))["p"]
        self.assertEqual(projected, QPointF(63.0, 43.0))

    def test_non_positive_viewport_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            project_points({"p": (0.0, 0.0, 0.0)}, FRONT_VIEW, (0, 100))


if __name__ == "__main__":
    unittest.main()
