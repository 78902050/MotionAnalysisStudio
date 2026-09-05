import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app.io.transactions import ProjectTransaction
from app.project import manager as project_manager_module
from app.project.manager import ProjectManager
from app.project.migration import migrate_v2_manifest


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

    def test_manifest_path_cannot_escape_project_root(self) -> None:
        self.assertTrue(
            hasattr(project_manager_module, "ProjectPathError"),
            "ProjectPathError must distinguish unsafe manifest paths",
        )
        project_path_error = project_manager_module.ProjectPathError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "项目"
            project = ProjectManager.create(root, "路径边界")
            project.manifest["paths"]["quality_report"] = "../outside.json"

            with self.assertRaises(project_path_error):
                project.path_for("quality_report")

            project.manifest["paths"]["quality_report"] = str(Path(directory) / "absolute.json")
            with self.assertRaises(project_path_error):
                project.path_for("quality_report")

    def test_open_v3_repairs_missing_project_layout_without_changing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "项目"
            project = ProjectManager.create(root, "布局修复")
            manifest_before = json.dumps(project.manifest, ensure_ascii=False, sort_keys=True)
            (root / "corrections" / "history.jsonl").unlink()
            (root / "corrections" / "sessions").rmdir()

            opened = ProjectManager.open(root)

            self.assertFalse(opened.migrated)
            self.assertTrue((root / "corrections" / "sessions").is_dir())
            self.assertTrue((root / "corrections" / "history.jsonl").is_file())
            self.assertEqual(
                json.dumps(opened.manifest, ensure_ascii=False, sort_keys=True), manifest_before
            )

    def test_v2_migration_retry_uses_stable_project_id(self) -> None:
        legacy = {"schema_version": 2, "name": "重试项目"}

        try:
            first = migrate_v2_manifest(deepcopy(legacy), project_identity="D:/projects/retry")
            second = migrate_v2_manifest(deepcopy(legacy), project_identity="D:/projects/retry")
        except TypeError as exc:
            self.fail(f"migration does not support a stable project identity: {exc}")

        self.assertEqual(first["project_id"], second["project_id"])

    def test_open_recovers_incomplete_project_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "项目"
            ProjectManager.create(root, "自动恢复")
            data_path = root / "reports" / "state.json"
            data_path.write_text('{"value": 1}\n', encoding="utf-8")
            transaction = ProjectTransaction(root, transaction_id="tx-open-recovery")
            transaction.prepare_json("reports/state.json", {"value": 2})
            transaction.prepare_json("reports/second.json", {"value": 3})
            real_replace = os.replace
            replacements = 0

            def fail_second_replace(source, destination):
                nonlocal replacements
                replacements += 1
                if replacements == 2:
                    raise OSError("interrupted commit")
                return real_replace(source, destination)

            with patch("app.io.transactions.os.replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(OSError, "interrupted commit"):
                    transaction.commit()
            self.assertEqual(json.loads(data_path.read_text(encoding="utf-8")), {"value": 2})

            opened = ProjectManager.open(root)

            self.assertEqual(json.loads(data_path.read_text(encoding="utf-8")), {"value": 1})
            self.assertEqual(opened.recovered_transactions, ("tx-open-recovery",))


if __name__ == "__main__":
    unittest.main()
