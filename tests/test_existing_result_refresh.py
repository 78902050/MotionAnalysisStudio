import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter
from app.project.manager import ProjectManager


FIXTURE_POSE = Path("tests/fixtures/real_data/pose/cam01_json/cam01_000000.json")
FIXTURE_TRC = Path("tests/fixtures/real_data/pose3d/three_frames_65_markers.trc")


class ExistingResultRefreshTests(unittest.TestCase):
    def test_registration_repairs_stale_manifest_without_replacing_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "旧登记试次"
            project = ProjectManager.create(root, "旧项目名")
            project.manifest["custom_user_state"] = {"keep": True}
            project.save_manifest()
            history = root / "corrections" / "history.jsonl"
            history.write_text('{"existing": true}\n', encoding="utf-8")
            pose = root / "pose" / "cam01_json" / "cam01_000000.json"
            pose.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURE_POSE, pose)
            trc = root / "pose-3d" / "trial_P0.trc"
            shutil.copy2(FIXTURE_TRC, trc)
            original_project_id = project.manifest["project_id"]

            candidate = ExistingResultDiscovery().discover_one(root)
            refreshed = ExistingResultImporter().register(candidate)

            self.assertEqual(refreshed.manifest["project_id"], original_project_id)
            self.assertEqual(refreshed.manifest["custom_user_state"], {"keep": True})
            self.assertEqual(refreshed.manifest["name"], "旧项目名")
            self.assertEqual(refreshed.manifest["cameras"], [{"camera_id": "cam01"}])
            self.assertEqual(
                refreshed.manifest["imported_artifacts"]["pose_2d_files"],
                1,
            )
            self.assertEqual(
                refreshed.manifest["imported_artifacts"]["trc_files"],
                [str(trc.resolve())],
            )
            self.assertEqual(
                refreshed.manifest["stages"]["poseEstimation"]["status"],
                "completed",
            )
            self.assertEqual(history.read_text(encoding="utf-8"), '{"existing": true}\n')


if __name__ == "__main__":
    unittest.main()
