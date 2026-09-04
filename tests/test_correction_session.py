import json
import tempfile
import unittest
from pathlib import Path

from app.correction.history import CorrectionHistory
from app.correction.session import CorrectionSession
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.pose_editor.model import PoseDocument


def _target(frame: int = 12) -> CorrectionTarget:
    return CorrectionTarget(
        FrameAddress("cam01", "pose2d", frame),
        PersonAddress("person-01", "segment-01", 0),
        KeypointAddress("coco17", "left_wrist", 0),
    )


class CorrectionSessionTests(unittest.TestCase):
    def _session(self, root: Path) -> CorrectionSession:
        path = root / "pose" / "cam01.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "camera": "cam01",
                    "model_name": "coco17",
                    "keypoint_names": ["left_wrist"],
                    "frames": [
                        {
                            "frame": 12,
                            "people": [
                                {
                                    "project_person_id": "person-01",
                                    "keypoints": {"left_wrist": {"x": 10, "y": 20, "confidence": 0.2}},
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return CorrectionSession(
            PoseDocument(path, project_root=root),
            project_root=root,
            session_id="session-1",
        )

    def test_apply_point_defaults_to_confidence_one_and_undo_redo_restores_triple(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._session(Path(directory))
            target = _target()
            session.apply_point(target, 30.0, 40.0)
            self.assertEqual(session.document.value_at(target), (30.0, 40.0, 1.0))

            session.undo()
            self.assertEqual(session.document.value_at(target), (10.0, 20.0, 0.2))
            session.redo()
            self.assertEqual(session.document.value_at(target), (30.0, 40.0, 1.0))

    def test_disposition_persists_and_cancelled_navigation_keeps_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._session(root)
            first = _target()
            second = _target(13)
            session.open([first, second])
            issue_id = session.issue_ids[0]
            session.set_disposition(issue_id, "handled", "已确认")
            reloaded = CorrectionSession(
                session.document,
                project_root=root,
                session_id="session-1",
            )
            self.assertEqual(reloaded.disposition(issue_id).status, "handled")

            session.apply_point(first, 30.0, 40.0)
            self.assertFalse(session.navigate_to(second, decision="cancel"))
            self.assertEqual(session.current(), first)

    def test_reset_frame_only_discards_unsaved_changes_on_that_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._session(Path(directory))
            target = _target()
            session.apply_point(target, 30.0, 40.0)
            session.reset_frame(12)
            self.assertEqual(session.document.value_at(target), (10.0, 20.0, 0.2))
            self.assertFalse(session.has_unsaved_changes())

    def test_apply_then_undo_saves_no_ghost_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._session(root)
            target = _target()

            session.apply_point(target, 30.0, 40.0)
            session.undo()
            count, operation_ids = session.save()

            self.assertEqual((count, operation_ids), (0, []))
            self.assertEqual(CorrectionHistory(root).operations(), [])
            self.assertEqual(session.document.value_at(target), (10.0, 20.0, 0.2))

    def test_multiple_edits_then_undo_saves_one_net_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._session(root)
            target = _target()

            session.apply_point(target, 30.0, 40.0)
            session.apply_point(target, 50.0, 60.0, confidence=0.8)
            session.undo()
            count, _ = session.save(note="净变化")

            self.assertEqual(count, 1)
            operation = CorrectionHistory(root).operations()[0]
            self.assertEqual(operation.before, (10.0, 20.0, 0.2))
            self.assertEqual(operation.after, (30.0, 40.0, 1.0))
            self.assertEqual(session.document.value_at(target), operation.after)

    def test_undo_redo_history_matches_saved_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._session(root)
            target = _target()

            session.apply_point(target, 30.0, 40.0)
            session.undo()
            session.redo()
            count, _ = session.save()

            self.assertEqual(count, 1)
            operation = CorrectionHistory(root).operations()[0]
            self.assertEqual(operation.before, (10.0, 20.0, 0.2))
            self.assertEqual(operation.after, session.document.value_at(target))


if __name__ == "__main__":
    unittest.main()
