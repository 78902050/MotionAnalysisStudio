import json
import os
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.adapters.pose2sim.pose2d_repository import Pose2DRepository
from app.correction.history import CorrectionHistory
from app.correction.session import CorrectionSession
from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.pose_editor.model import PoseDocument
from app.project.manager import ProjectManager


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

    def test_save_transaction_rolls_back_every_project_file_on_partial_failure(self) -> None:
        for failure_index in range(1, 5):
            with self.subTest(failure_index=failure_index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ProjectManager.create(root, "事务修正")
                pose_path = root / "pose" / "cam01.json"
                pose_path.write_text(json.dumps(_pose_payload()), encoding="utf-8")
                document = PoseDocument(pose_path, project_root=root)
                session = CorrectionSession(document, project_root=root, session_id="session-1")
                session.apply_point(_target(), 30.0, 40.0)
                original_pose = pose_path.read_bytes()
                original_manifest = (root / "manifest.json").read_bytes()
                original_history = (root / "corrections" / "history.jsonl").read_bytes()
                backup = CorrectionHistory(root).backup_path(pose_path)
                real_replace = os.replace
                replacements = 0

                def fail_selected_replace(source, target):
                    nonlocal replacements
                    replacements += 1
                    if replacements == failure_index:
                        raise OSError("injected replacement failure")
                    return real_replace(source, target)

                with patch("app.io.transactions.os.replace", side_effect=fail_selected_replace):
                    with self.assertRaisesRegex(OSError, "injected replacement failure"):
                        session.save()

                self.assertEqual(pose_path.read_bytes(), original_pose)
                self.assertEqual((root / "manifest.json").read_bytes(), original_manifest)
                self.assertEqual(
                    (root / "corrections" / "history.jsonl").read_bytes(), original_history
                )
                self.assertFalse(backup.exists())
                self.assertTrue(session.has_unsaved_changes())

    def test_successful_save_updates_manifest_and_invalidates_from_person_association(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "依赖失效")
            for stage in project.manifest["stages"].values():
                stage["status"] = "completed"
            project.save_manifest()
            pose_path = root / "pose" / "cam01.json"
            pose_path.write_text(json.dumps(_pose_payload()), encoding="utf-8")
            session = CorrectionSession(
                PoseDocument(pose_path, project_root=root),
                project_root=root,
                session_id="session-1",
            )
            session.apply_point(_target(), 30.0, 40.0)

            count, operation_ids = session.save()
            saved_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(count, 1)
            self.assertEqual(saved_manifest["stages"]["poseEstimation"]["status"], "completed")
            self.assertEqual(
                saved_manifest["stages"]["personAssociation"]["status"], "stale"
            )
            self.assertEqual(saved_manifest["stages"]["triangulation"]["status"], "stale")
            self.assertIn(operation_ids[0], saved_manifest["manual_pose_edits"])

    def test_restore_audits_added_removed_and_modified_keypoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose_path = root / "pose" / "cam01.json"
            pose_path.parent.mkdir()
            original = _pose_payload()
            original["keypoint_names"].append("right_elbow")
            original["frames"][0]["people"][0]["keypoints"]["right_elbow"] = {
                "x": 15.0,
                "y": 25.0,
                "confidence": 0.6,
            }
            pose_path.write_text(json.dumps(original), encoding="utf-8")
            history = CorrectionHistory(root)
            self.assertTrue(history.backup_once(pose_path))
            current = copy.deepcopy(original)
            points = current["frames"][0]["people"][0]["keypoints"]
            points["left_wrist"]["x"] = 99.0
            del points["right_elbow"]
            points["temporary_point"] = {"x": 1.0, "y": 2.0, "confidence": 0.3}
            pose_path.write_text(json.dumps(current), encoding="utf-8")

            count = history.restore_file(pose_path, "结构恢复")

            self.assertEqual(count, 3)
            self.assertEqual(
                {operation.change_kind for operation in history.operations()},
                {"added", "removed", "modified"},
            )
            self.assertEqual(json.loads(pose_path.read_text(encoding="utf-8")), original)

    def test_restore_audits_pose2sim_flat_keypoint_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectManager.create(root, "Pose2Sim 恢复")
            pose_path = root / "pose" / "cam01_json" / "cam01_000012.json"
            pose_path.parent.mkdir(parents=True)
            original = {
                "version": 1.3,
                "people": [
                    {
                        "person_id": [-1],
                        "pose_keypoints_2d": [10.0, 20.0, 0.2],
                    }
                ],
            }
            pose_path.write_text(json.dumps(original), encoding="utf-8")
            repository = Pose2DRepository(
                root / "pose",
                ("left_wrist",),
                project_root=root,
                model_name="coco17",
            )
            document = repository.load_frame("cam01", 12)
            session = CorrectionSession(document, project_root=root, session_id="flat-session")
            session.apply_point(_target(), 30.0, 40.0)
            self.assertEqual(session.save(note="flat save")[0], 1)

            history = CorrectionHistory(root)
            self.assertEqual(history.restore_file(pose_path, "flat restore"), 1)

            restored = json.loads(pose_path.read_text(encoding="utf-8"))
            self.assertEqual(restored, original)
            operation = history.operations()[-1]
            self.assertEqual(operation.target.keypoint.keypoint_name, "left_wrist")
            self.assertEqual(operation.before, (30.0, 40.0, 1.0))
            self.assertEqual(operation.after, (10.0, 20.0, 0.2))


if __name__ == "__main__":
    unittest.main()
