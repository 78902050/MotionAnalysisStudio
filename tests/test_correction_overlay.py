import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.gui.pages.correction_page import CorrectionCanvas


class CorrectionOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_canvas_tracks_only_edges_with_visible_endpoints(self) -> None:
        canvas = CorrectionCanvas()
        canvas.set_pose_points(
            {
                "LShoulder": (10.0, 20.0, 0.9),
                "LElbow": (20.0, 30.0, 0.8),
                "LWrist": (30.0, 40.0, 0.0),
            },
            edges=(("LShoulder", "LElbow"), ("LElbow", "LWrist")),
        )

        self.assertEqual(canvas.point_count, 3)
        self.assertEqual(canvas.edge_count, 1)
        canvas.clear()
        self.assertEqual(canvas.edge_count, 0)

    def test_unknown_model_can_draw_points_without_edges(self) -> None:
        canvas = CorrectionCanvas()
        canvas.set_pose_points({"index-000": (10.0, 20.0, 0.9)}, edges=())
        self.assertEqual(canvas.point_count, 1)
        self.assertEqual(canvas.edge_count, 0)

    def test_left_drag_on_canvas_background_pans_a_zoomed_view(self) -> None:
        canvas = CorrectionCanvas()
        canvas.resize(400, 300)
        canvas.set_data_extent(200, 100)
        canvas._zoom = 2.0
        canvas.show()
        self.application.processEvents()
        before = canvas._image_rect().center()

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(canvas, QPoint(70, 45), delay=1)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 45))
        self.application.processEvents()

        after = canvas._image_rect().center()
        self.assertEqual(after - before, QPoint(50, 25))
        canvas.close()

    def test_left_and_right_skeleton_edges_use_distinct_side_colors(self) -> None:
        canvas = CorrectionCanvas()
        canvas.resize(200, 100)
        canvas.set_data_extent(200, 100)
        canvas.set_pose_points(
            {
                "LShoulder": (20.0, 25.0, 1.0),
                "LElbow": (80.0, 25.0, 1.0),
                "RShoulder": (120.0, 75.0, 1.0),
                "RElbow": (180.0, 75.0, 1.0),
            },
            edges=(("LShoulder", "LElbow"), ("RShoulder", "RElbow")),
        )
        image = QImage(200, 100, QImage.Format.Format_ARGB32)

        canvas.render(image)

        left = image.pixelColor(50, 25)
        right = image.pixelColor(150, 75)
        self.assertGreater(left.blue(), left.red())
        self.assertGreater(right.red(), right.blue())
        self.assertNotEqual(left.name(), right.name())

    def test_wheel_zoom_keeps_image_coordinate_under_cursor(self) -> None:
        canvas = CorrectionCanvas()
        canvas.resize(400, 300)
        canvas.set_data_extent(200, 100)
        cursor = QPointF(110, 120)
        before = canvas._widget_to_image(cursor)
        event = QWheelEvent(
            cursor,
            cursor,
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        canvas.wheelEvent(event)

        after = canvas._widget_to_image(cursor)
        self.assertAlmostEqual(after.x(), before.x(), places=6)
        self.assertAlmostEqual(after.y(), before.y(), places=6)


if __name__ == "__main__":
    unittest.main()
