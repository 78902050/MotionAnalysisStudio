import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.correction.history import CorrectionHistory
from app.correction.session import CorrectionSession
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.pose_editor.model import PoseDocument


def _pose_payload(x: float = 10.0, confidence: float = 0.2) -> dict[str, object]:
    return {
        "camera": "cam01",
        "model_name": "coco17",
        "keypoint_names": ["left_wrist"],
        "frames": [
            {
                "frame": 12,
                "people": [
                    {
                        "project_person_id": "person-01",
                        "raw_person_index": 0,
                        "track_segment_id": "segment-01",
                        "keypoints": {
                            "left_wrist": {"x": x, "y": 20.0, "confidence": confidence}
                        },
                    }
                ],
            }
        ],
    }


def _target() -> CorrectionTarget:
    return CorrectionTarget(
        FrameAddress("cam01", "pose2d", 12),
        PersonAddress("person-01", "segment-01", 0),
        KeypointAddress("coco17", "left_wrist", 0),
    )


class CorrectionHistoryTests(unittest.TestCase):
    def test_first_save_is_backed_up_once_and_restore_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose_path = root / "pose" / "cam01.json"
            pose_path.parent.mkdir()
            pose_path.write_text(json.dumps(_pose_payload(), ensure_ascii=False), encoding="utf-8")
            document = PoseDocument(pose_path, project_root=root)
            session = CorrectionSession(document, project_root=root, session_id="session-1")

            session.apply_point(_target(), 30.0, 40.0)
            count, operation_ids = session.save(note="first")
            backup = root / "corrections" / "backups" / "pose" / "cam01_json" / "cam01.json"
            first_backup = backup.read_text(encoding="utf-8")

            self.assertEqual(count, 1)
            self.assertEqual(len(operation_ids), 1)
            self.assertTrue(backup.is_file())
            self.assertIn('"before":[10.0,20.0,0.2]', (
                root / "corrections" / "history.jsonl"
            ).read_text(encoding="utf-8"))

            session.apply_point(_target(), 50.0, 60.0, confidence=0.8)
            session.save(note="second")
            self.assertEqual(backup.read_text(encoding="utf-8"), first_backup)

            restored_count = CorrectionHistory(root).restore_file(pose_path, "撤销验证")
            restored = json.loads(pose_path.read_text(encoding="utf-8"))
            point = restored["frames"][0]["people"][0]["keypoints"]["left_wrist"]
            self.assertEqual(restored_count, 1)
            self.assertEqual((point["x"], point["y"], point["confidence"]), (10.0, 20.0, 0.2))
            self.assertEqual(CorrectionHistory(root).restore_file(pose_path, "重复恢复"), 0)

    def test_atomic_failure_keeps_pose_json_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose_path = root / "pose" / "cam01.json"
            pose_path.parent.mkdir()
            pose_path.write_text(json.dumps(_pose_payload()), encoding="utf-8")
            document = PoseDocument(pose_path, project_root=root)
            session = CorrectionSession(document, project_root=root, session_id="session-1")
            session.apply_point(_target(), 30.0, 40.0)

            with patch("app.io.atomic.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    session.save()

            self.assertEqual(json.loads(pose_path.read_text(encoding="utf-8")), _pose_payload())

    def test_corrupt_history_is_reported_instead_of_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history_path = root / "corrections" / "history.jsonl"
            history_path.parent.mkdir(parents=True)
            history_path.write_text('{"operation_id":"valid"}\n{"operation_id":"broken"', encoding="utf-8")

            with self.assertRaises(ValueError) as context:
                CorrectionHistory(root).operations()

            self.assertIn("line 2", str(context.exception))


if __name__ == "__main__":
    unittest.main()
