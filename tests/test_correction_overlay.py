import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


if __name__ == "__main__":
    unittest.main()
