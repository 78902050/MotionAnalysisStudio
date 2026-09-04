import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.project.manager import ProjectManager
from app.quality.audit import QualityAuditService
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class QualityAuditTests(unittest.TestCase):
    def _project_with_quality_inputs(self, root: Path) -> ProjectManager:
        project = ProjectManager.create(root, "质量测试")
        project.manifest["people"] = [
            {"project_person_id": "person-01", "display_name": "运动员 1"},
            {"project_person_id": "person-02", "display_name": "运动员 2"},
        ]
        project.save_manifest()
        _write_json(
            root / "calibration" / "normalized" / "cameras.json",
            {"cameras": [{"camera_id": "cam01"}, {"camera_id": "cam02"}]},
        )
        _write_json(
            root / "synchronization" / "mapping.json",
            {"mappings": [{"camera": "cam01", "source_frame": 0, "target_frame": 0}]},
        )
        for camera in ("cam01", "cam02"):
            _write_json(
                root / "pose" / f"{camera}.json",
                {
                    "camera": camera,
                    "model_name": "coco17",
                    "keypoint_names": ["right_ankle", "left_wrist"],
                    "frames": [
                        {
                            "frame": 0,
                            "people": [
                                {
                                    "raw_person_index": 0,
                                    "keypoints": {
                                        "left_wrist": {"x": 10, "y": 20, "confidence": 0.9}
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
        _write_json(
            root / "pose-associated" / "results.json",
            {
                "frames": [
                    {
                        "frame": 0,
                        "people": [
                            {
                                "project_person_id": "person-01",
                                "raw_person_index": 0,
                                "track_segment_id": "segment-01",
                            }
                        ],
                    }
                ]
            },
        )
        _write_json(
            root / "pose-3d" / "results.json",
            {
                "model_name": "coco17",
                "keypoint_names": ["left_wrist"],
                "frames": [
                    {
                        "frame": 0,
                        "people": [
                            {
                                "project_person_id": "person-01",
                                "raw_person_index": 0,
                                "track_segment_id": "segment-01",
                                "keypoints": {
                                    "left_wrist": {
                                        "xyz": [1.0, 2.0, 3.0],
                                        "confidence": 0.9,
                                        "reprojection_error": 8.0,
                                        "reprojection_error_by_camera": {"cam01": 2.0, "cam02": 8.0},
                                        "observed_cameras": ["cam01", "cam02"],
                                        "interpolated": False,
                                    }
                                },
                            }
                        ],
                    }
                ],
            },
        )
        return project

    def test_audit_separates_population_counts_and_returns_complete_semantic_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with_quality_inputs(Path(directory))

            report = QualityAuditService().analyze(project)

            metrics = report.metrics()
            self.assertEqual(metrics["actual_people_count"], 2)
            self.assertEqual(metrics["2d_detection_people_count"], 2)
            self.assertEqual(metrics["associated_people_count"], 1)
            self.assertEqual(metrics["track_segment_count"], 1)
            self.assertEqual(metrics["coverage_start_frame"], 0)
            self.assertEqual(metrics["coverage_end_frame"], 0)
            self.assertEqual(metrics["camera_contribution.cam01"], 1)
            self.assertEqual(metrics["camera_contribution.cam02"], 1)
            self.assertEqual(metrics["valid_keypoint_rate"], 1.0)
            self.assertEqual(metrics["missing_rate"], 0.0)
            self.assertEqual(metrics["interpolated_rate"], 0.0)
            self.assertEqual(metrics["average_reprojection_error"], 5.0)
            self.assertEqual(metrics["participating_camera_count"], 2.0)
            self.assertEqual(metrics["missing_rate"], 0.0)
            self.assertEqual(metrics["interpolated_rate"], 0.0)
            self.assertEqual(metrics["average_reprojection_error"], 5.0)
            self.assertEqual(metrics["participating_camera_count"], 2.0)

            reprojection_issues = [issue for issue in report.issues() if issue.kind == "reprojection"]
            self.assertEqual(len(reprojection_issues), 1)
            target = report.target(reprojection_issues[0].issue_id)
            self.assertIsNotNone(target)
            assert target is not None
            self.assertEqual(target.address.camera, "cam02")
            self.assertEqual(target.address.timeline, "pose2d")
            self.assertEqual(target.address.frame, 0)
            self.assertEqual(target.person.project_person_id, "person-01")
            self.assertEqual(target.keypoint.keypoint_name, "left_wrist")
            self.assertEqual(target.keypoint.source_index, 1)

    def test_save_writes_current_report_and_versioned_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with_quality_inputs(Path(directory))
            service = QualityAuditService()
            report = service.analyze(project)

            service.save(report)

            current = project.path_for("quality_report")
            self.assertTrue(current.is_file())
            self.assertTrue((current.parent / "history" / f"{report.report_id}.json").is_file())
            loaded = QualityReportStore(project).load_current()
            self.assertIsInstance(loaded, QualityReport)
            self.assertEqual(loaded.report_id, report.report_id)

    def test_missing_quality_layer_produces_blocking_issue_instead_of_empty_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "缺失输入")

            report = QualityAuditService().analyze(project)

            self.assertTrue(report.issues())
            self.assertTrue(any(issue.severity == "blocking" for issue in report.issues()))
            self.assertTrue(any(issue.kind == "input_invalid" for issue in report.issues()))
            self.assertIn("pose-3d", " ".join(issue.message for issue in report.issues()))

    def test_report_save_rolls_back_current_when_history_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with_quality_inputs(Path(directory))
            store = QualityReportStore(project)
            before = QualityReport.create("quality-before", {"missing_rate": 0.2}, (), {})
            store.save(before)
            current = project.path_for("quality_report")
            before_bytes = current.read_bytes()
            after = QualityReport.create("quality-after", {"missing_rate": 0.1}, (), {})
            real_replace = os.replace
            replacements = 0

            def fail_second_replace(source, target):
                nonlocal replacements
                replacements += 1
                if replacements == 2:
                    raise OSError("history write failed")
                return real_replace(source, target)

            with patch("app.io.transactions.os.replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(OSError, "history write failed"):
                    store.save(after)

            self.assertEqual(current.read_bytes(), before_bytes)
            self.assertFalse((current.parent / "history" / "quality-after.json").exists())


if __name__ == "__main__":
    unittest.main()


