import json
import tempfile
import unittest
from pathlib import Path

from app.project.manager import ProjectManager


class ProjectManagerTests(unittest.TestCase):
    def test_create_generates_v3_manifest_and_complete_work_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文项目"
            project = ProjectManager.create(root, "第一次试验")

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 3)
            self.assertEqual(manifest["name"], "第一次试验")
            self.assertTrue(manifest["project_id"])
            self.assertEqual(project.path_for("quality_report"), root / "reports" / "quality" / "current.json")

            required = (
                "config",
                "calibration/source",
                "calibration/normalized",
                "calibration/reports",
                "pose",
                "pose-sync",
                "pose-associated",
                "pose-3d",
                "synchronization",
                "kinematics",
                "reports/quality/history",
                "reports/metrics",
                "reports/comparisons",
                "corrections/sessions",
                "corrections/backups/pose",
                "corrections/backups/association",
                "logs",
            )
            for relative in required:
                self.assertTrue((root / relative).is_dir(), relative)
            self.assertTrue((root / "corrections" / "history.jsonl").is_file())

    def test_v2_open_migrates_once_and_preserves_manual_edits_and_completed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "旧项目"
            root.mkdir()
            old_manifest = {
                "schema_version": 2,
                "name": "旧项目",
                "manual_pose_edits": [{"camera": "cam01", "frame": 8, "x": 10.5}],
                "stages": {"poseEstimation": {"status": "completed", "generation": 2}},
                "paths": {"quality_report": "reports/quality/current.json"},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(old_manifest, ensure_ascii=False), encoding="utf-8")

            first = ProjectManager.open(root)
            migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
            first_snapshot = json.dumps(migrated, ensure_ascii=False, sort_keys=True)

            self.assertTrue(first.migrated)
            self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["manual_pose_edits"], old_manifest["manual_pose_edits"])
            self.assertEqual(migrated["stages"]["poseEstimation"]["status"], "completed")
            self.assertEqual(migrated["migration"]["source_schema_version"], 2)
            self.assertTrue(migrated["migration"]["migrated_at"])

            second = ProjectManager.open(root)
            second_snapshot = json.dumps(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                ensure_ascii=False,
                sort_keys=True,
            )
            self.assertFalse(second.migrated)
            self.assertEqual(first_snapshot, second_snapshot)

    def test_open_v3_is_noop_and_unknown_manifest_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "项目"
            project = ProjectManager.create(root, "试验")
            opened = ProjectManager.open(root)

            self.assertFalse(opened.migrated)
            self.assertEqual(opened.manifest, project.manifest)
            with self.assertRaises(KeyError):
                opened.path_for("not-a-manifest-path")


if __name__ == "__main__":
    unittest.main()
