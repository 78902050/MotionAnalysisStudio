import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from app.application.quality_correction_service import CorrectionResolution
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.gui.pages.correction_page import CorrectionCanvas, CorrectionPage
from app.domain.pose2d import FramePose, PersonPose, PoseKeypoint


def _target(frame: int, timeline: str = "raw") -> CorrectionTarget:
    return CorrectionTarget(
        FrameAddress("camA", timeline, frame),  # type: ignore[arg-type]
        PersonAddress("person-01", "track-01", 0),
        KeypointAddress("coco17", "left_wrist", 1),
    )


class _Document:
    def __init__(self, target: CorrectionTarget) -> None:
        self.target = target
        self.value = (10.0, 20.0, 0.4)

    def value_at(self, target: CorrectionTarget):
        if target != self.target:
            raise KeyError(target)
        return self.value

    def frame_pose(self) -> FramePose:
        return FramePose(
            "camA",
            12,
            (
                PersonPose(
                    0,
                    "person-01",
                    "track-01",
                    (
                        PoseKeypoint("nose", 5.0, 6.0, 0.8),
                        PoseKeypoint("left_wrist", *self.value),
                    ),
                ),
            ),
            Path("pose/camA_000012.json"),
        )


class _Session:
    def __init__(self, target: CorrectionTarget) -> None:
        self.session_id = "session-ui"
        self.document = _Document(target)
        self._undo: list[tuple[float, float, float]] = []
        self._redo: list[tuple[float, float, float]] = []
        self.save_calls = 0

    def apply_point(self, target, x, y, confidence=1.0):
        self._undo.append(self.document.value)
        self._redo.clear()
        self.document.value = (float(x), float(y), float(confidence))

    def undo(self):
        if self._undo:
            self._redo.append(self.document.value)
            self.document.value = self._undo.pop()

    def redo(self):
        if self._redo:
            self._undo.append(self.document.value)
            self.document.value = self._redo.pop()

    def reset_frame(self, _frame):
        self.document.value = (10.0, 20.0, 0.4)
        self._undo.clear()
        self._redo.clear()

    def save(self, note=""):
        del note
        self.save_calls += 1
        return 1, ["op-ui"]

    def has_unsaved_changes(self):
        return bool(self._undo)

    def discard_unsaved(self):
        self.reset_frame(12)

    def previous_issue(self):
        return self.document.target

    def next_issue(self):
        return self.document.target


class _Controller:
    def __init__(self) -> None:
        self.reruns: list[str] = []

    def request_correction_rerun(self, session_id: str) -> bool:
        self.reruns.append(session_id)
        return True


class CorrectionWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _resolution(self, blocker: str | None = None) -> CorrectionResolution:
        return CorrectionResolution(
            "issue-ui",
            _target(10, "pose2d"),
            None if blocker else _target(12),
            10,
            12,
            "mapping.json",
            Path("pose/camA.json") if blocker is None else None,
            None,
            blocker,
        )

    def test_resolution_drives_frames_point_edit_undo_redo_and_reset(self) -> None:
        resolution = self._resolution()
        assert resolution.edit_target is not None
        session = _Session(resolution.edit_target)
        page = CorrectionPage(session=session)

        page.open_resolution(resolution, session)
        self.assertEqual(page.synchronized_frame.text(), "10")
        self.assertEqual(page.raw_frame.text(), "12")
        self.assertEqual(page.x_value.value(), 10)
        self.assertEqual(page.y_value.value(), 20)

        page.nudge_selected(1, 0)
        self.assertEqual(session.document.value, (11.0, 20.0, 1.0))
        page.undo_selected()
        self.assertEqual(session.document.value, (10.0, 20.0, 0.4))
        page.redo_selected()
        self.assertEqual(session.document.value, (11.0, 20.0, 1.0))
        page.reset_selected_frame()
        self.assertEqual(session.document.value, (10.0, 20.0, 0.4))

    def test_save_and_rerun_uses_application_controller(self) -> None:
        resolution = self._resolution()
        assert resolution.edit_target is not None
        session = _Session(resolution.edit_target)
        controller = _Controller()
        page = CorrectionPage(session=session, controller=controller)
        page.open_resolution(resolution, session)
        page.nudge_selected(2, 0)

        page.save_and_rerun()

        self.assertEqual(session.save_calls, 1)
        self.assertEqual(controller.reruns, ["session-ui"])

    def test_blocked_resolution_disables_edit_and_explains_reason(self) -> None:
        page = CorrectionPage()

        page.open_resolution(self._resolution("人物候选不唯一"), None)

        self.assertFalse(page.save_button.isEnabled())
        self.assertFalse(page.x_value.isEnabled())
        self.assertIn("人物候选不唯一", page.session_status.text())

    def test_real_frame_is_rendered_and_canvas_drag_updates_selected_point(self) -> None:
        resolution = self._resolution()
        assert resolution.edit_target is not None
        session = _Session(resolution.edit_target)
        page = CorrectionPage(session=session)
        page.set_cameras(["camA"])
        page.open_resolution(resolution, session)
        image = np.zeros((24, 32, 3), dtype=np.uint8)

        page._on_frame_ready("camA", 12, image)
        canvas = page.findChild(CorrectionCanvas, "correction_canvas_1")

        self.assertIsNotNone(canvas)
        assert canvas is not None
        self.assertTrue(canvas.has_frame)
        self.assertEqual(canvas.point_count, 2)
        canvas.point_moved.emit(31.5, 42.5)
        self.assertEqual(session.document.value, (31.5, 42.5, 1.0))

    def test_late_frame_from_previous_request_does_not_replace_current_view(self) -> None:
        page = CorrectionPage()
        page.set_cameras(["camA"])
        page.set_view_addresses({"camA": FrameAddress("camA", "raw", 20)})
        current = np.full((8, 8, 3), 20, dtype=np.uint8)
        stale = np.full((8, 8, 3), 10, dtype=np.uint8)

        page._on_frame_ready("camA", 20, current)
        page._on_frame_ready("camA", 10, stale)

        self.assertIn("20", page._view_labels[0].text())
        self.assertNotIn("10", page._view_labels[0].text())

    def test_opening_issue_prioritizes_its_camera_in_single_view(self) -> None:
        resolution = self._resolution()
        assert resolution.edit_target is not None
        page = CorrectionPage(session=_Session(resolution.edit_target))
        page.set_cameras(["camB", "camA"])
        page.set_view_count(1)

        page.open_resolution(resolution, page.session)

        self.assertEqual(page._view_cards[0].property("camera"), "camA")
        self.assertEqual(page.camera_selector.currentText(), "camA")


if __name__ == "__main__":
    unittest.main()
