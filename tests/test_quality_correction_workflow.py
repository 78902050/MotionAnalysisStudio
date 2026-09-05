import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.domain.addresses import CorrectionTarget, FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.correction.history import CorrectionHistory
from app.project.manager import ProjectManager


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _person(raw_index: int, person_id: str | None, wrist_x: float) -> dict[str, object]:
    result: dict[str, object] = {
        "raw_person_index": raw_index,
        "keypoints": {
            "nose": {"x": wrist_x - 5, "y": 10, "confidence": 0.8},
            "left_wrist": {"x": wrist_x, "y": 20, "confidence": 0.4},
        },
    }
    if person_id is not None:
        result["project_person_id"] = person_id
    return result


class QualityCorrectionWorkflowTests(unittest.TestCase):
    def _project(self, root: Path, *, ambiguous: bool = False) -> ProjectManager:
        project = ProjectManager.create(root, "质检修正")
        project.manifest["cameras"] = [{"camera_id": "camA"}]
        project.manifest["people"] = [{"project_person_id": "person-left"}]
        project.save_manifest()
        _write_json(
            root / "synchronization" / "mapping.json",
            {"offsets": [{"camera": "camA", "frame_delta": 2, "source": "manual-sync"}]},
        )
        # The list order differs from raw_person_index on purpose.
        _write_json(
            root / "pose" / "camA.json",
            {
                "camera": "camA",
                "model_name": "coco17",
                "keypoint_names": ["nose", "left_wrist"],
                "frames": [
                    {
                        "frame": 12,
                        "people": [
                            _person(1, None, 100),
                            _person(0, None, 10),
                        ],
                    }
                ],
            },
        )
        associated_people = [_person(1, "person-left", 100)]
        if ambiguous:
            associated_people.append(_person(0, "person-left", 10))
        _write_json(
            root / "pose-associated" / "results.json",
            {
                "frames": [
                    {"camera": "camA", "frame": 10, "people": associated_people}
                ]
            },
        )
        return project

    @staticmethod
    def _issue(keypoint: str = "left_wrist") -> QualityIssue:
        return QualityIssue(
            "issue-1",
            "reprojection",
            "warning",
            FrameAddress("camA", "pose2d", 10),
            PersonAddress("person-left"),
            KeypointAddress("coco17", keypoint, 1),
            "重投影误差过高",
        )

    def test_resolves_semantic_issue_to_mapped_raw_frame_and_correct_person(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            service = QualityCorrectionService(project)

            resolution = service.resolve_issue(self._issue())

            self.assertIsNone(resolution.blocker)
            self.assertEqual(resolution.synchronized_frame, 10)
            self.assertEqual(resolution.raw_frame, 12)
            self.assertEqual(resolution.mapping_source, "manual-sync")
            self.assertIsNotNone(resolution.edit_target)
            assert resolution.edit_target is not None
            self.assertEqual(resolution.edit_target.address.timeline, "raw")
            self.assertEqual(resolution.edit_target.address.frame, 12)
            self.assertEqual(resolution.edit_target.person.raw_person_index, 1)

            session = service.create_session(resolution)
            self.assertEqual(session.issue_ids, ("issue-1",))
            session.apply_point(resolution.edit_target, 33, 44)
            self.assertEqual(session.document.value_at(resolution.edit_target), (33.0, 44.0, 1.0))
            self.assertEqual(session.save(note="人工确认")[0], 1)

            payload = json.loads((project.root / "pose" / "camA.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["frames"][0]["people"][0]["keypoints"]["left_wrist"], {
                "x": 33.0,
                "y": 44.0,
                "confidence": 1.0,
            })
            self.assertEqual(payload["frames"][0]["people"][1]["keypoints"]["left_wrist"]["x"], 10)

    def test_ambiguous_person_mapping_blocks_editing_without_guessing(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        with tempfile.TemporaryDirectory() as directory:
            resolution = QualityCorrectionService(
                self._project(Path(directory), ambiguous=True)
            ).resolve_issue(self._issue())

            self.assertIsNotNone(resolution.blocker)
            self.assertIn("人物", resolution.blocker)
            self.assertIsNone(resolution.edit_target)

    def test_stale_report_raw_index_must_match_current_association(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            stale = QualityIssue(
                "stale-person-index",
                "reprojection",
                "warning",
                FrameAddress("camA", "pose2d", 10),
                PersonAddress("person-left", raw_person_index=0),
                KeypointAddress("coco17", "left_wrist", 1),
                "旧报告中的人物索引",
            )

            resolution = QualityCorrectionService(project).resolve_issue(stale)

            self.assertIsNone(resolution.edit_target)
            self.assertIn("人物", resolution.blocker or "")
            self.assertIn("不一致", resolution.blocker or "")

    def test_missing_mapping_and_unknown_keypoint_are_explicit_blockers(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            (project.root / "synchronization" / "mapping.json").unlink()
            missing_mapping = QualityCorrectionService(project).resolve_issue(self._issue())
            self.assertIn("同步", missing_mapping.blocker or "")

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            unknown_keypoint = QualityCorrectionService(project).resolve_issue(
                self._issue("not-a-keypoint")
            )
            self.assertIn("关节点", unknown_keypoint.blocker or "")

    def test_real_pose2sim_frame_file_can_open_edit_undo_and_save(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        fixture = Path("tests/fixtures/real_data/pose")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "真实二维帧")
            shutil.copytree(fixture, root / "pose", dirs_exist_ok=True)
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.manifest["people"] = [{"project_person_id": "person-01"}]
            project.save_manifest()
            _write_json(
                root / "synchronization" / "mapping.json",
                {"offsets": [{"camera": "cam01", "frame_delta": 0, "source": "sample-map"}]},
            )
            _write_json(
                root / "pose-associated" / "results.json",
                {
                    "frames": [
                        {
                            "camera": "cam01",
                            "frame": 0,
                            "people": [
                                {"project_person_id": "person-01", "raw_person_index": 0}
                            ],
                        }
                    ]
                },
            )
            issue = QualityIssue(
                "real-issue",
                "reprojection",
                "warning",
                FrameAddress("cam01", "pose2d", 0),
                PersonAddress("person-01"),
                KeypointAddress("halpe26", "nose", 0),
                "真实格式点位",
            )

            service = QualityCorrectionService(project)
            resolution = service.resolve_issue(issue)

            self.assertIsNone(resolution.blocker)
            self.assertTrue(resolution.pose_path.name.endswith("000000.json"))
            assert resolution.edit_target is not None
            session = service.create_session(resolution)
            self.assertEqual(session.issue_ids, ("real-issue",))
            before = session.document.value_at(resolution.edit_target)
            session.apply_point(resolution.edit_target, 11, 22)
            session.undo()
            self.assertEqual(session.document.value_at(resolution.edit_target), before)
            session.redo()
            self.assertEqual(session.save(note="真实格式确认")[0], 1)

            payload = json.loads(resolution.pose_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["people"][0]["pose_keypoints_2d"][:3], [11.0, 22.0, 1.0])
            operation = CorrectionHistory(root).operations()[-1]
            self.assertEqual(operation.target.person.project_person_id, "person-01")
            self.assertEqual(operation.session_id, session.session_id)

    def test_multiview_raw_addresses_use_each_cameras_mapping(self) -> None:
        from app.application.quality_correction_service import QualityCorrectionService

        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            project.manifest["cameras"].append({"camera_id": "camB"})
            project.save_manifest()
            _write_json(
                project.root / "synchronization" / "mapping.json",
                {
                    "offsets": [
                        {"camera": "camA", "frame_delta": 2, "source": "cam-a-map"},
                        {"camera": "camB", "frame_delta": -1, "source": "cam-b-map"},
                    ]
                },
            )

            addresses, failures = QualityCorrectionService(project).raw_view_addresses(
                10,
                ("camA", "camB"),
            )

            self.assertEqual(addresses["camA"], FrameAddress("camA", "raw", 12))
            self.assertEqual(addresses["camB"], FrameAddress("camB", "raw", 9))
            self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
