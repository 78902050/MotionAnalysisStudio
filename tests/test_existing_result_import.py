import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.project.discovery import ExistingResultDiscovery
from app.project.importer import ExistingResultImporter


FIXTURE_CALIBRATION = Path("tests/fixtures/real_data/calibration/camera_array.toml")
FIXTURE_POSE = Path("tests/fixtures/real_data/pose/cam01_json/cam01_000000.json")
FIXTURE_TRC = Path("tests/fixtures/real_data/pose3d/three_frames_65_markers.trc")


def _make_trial(root: Path, name: str, cameras: tuple[str, ...] = ("cam01",)) -> Path:
    trial = root / name
    for layer in ("pose", "pose-sync", "pose-associated"):
        for camera in cameras:
            directory = trial / layer / f"{camera}_json"
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURE_POSE, directory / f"{camera}_000000.json")
    (trial / "pose-3d").mkdir(parents=True)
    shutil.copy2(FIXTURE_TRC, trial / "pose-3d" / f"{name}.trc")
    (trial / "kinematics").mkdir()
    (trial / "kinematics" / f"{name}.mot").write_text("Coordinates\n", encoding="utf-8")
    return trial


class ExistingResultDiscoveryTests(unittest.TestCase):
    def test_discovers_one_processed_trial_without_video_or_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            date_root = Path(directory) / "8.14"
            date_root.mkdir()
            shutil.copy2(FIXTURE_CALIBRATION, date_root / "camera_array.toml")
            trial = _make_trial(date_root, "无视频试次", ("cam01", "can02"))

            candidate = ExistingResultDiscovery().discover_one(trial)

            self.assertEqual(candidate.root, trial.resolve())
            self.assertEqual(candidate.cameras, ("cam01", "can02"))
            self.assertEqual(candidate.artifacts.pose_2d, 2)
            self.assertEqual(candidate.artifacts.pose_sync, 2)
            self.assertEqual(candidate.artifacts.pose_associated, 2)
            self.assertEqual(len(candidate.artifacts.trc), 1)
            self.assertEqual(len(candidate.artifacts.kinematics), 1)
            self.assertEqual(candidate.calibration_path, (date_root / "camera_array.toml").resolve())
            self.assertEqual(candidate.config_state, "missing")
            self.assertFalse(candidate.has_video)

    def test_parent_scan_returns_trials_not_result_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            first = _make_trial(root / "8.14", "走路")
            second = _make_trial(root / "8.15", "起跑")

            candidates = ExistingResultDiscovery().scan(root)

            self.assertEqual(tuple(item.root for item in candidates), (first.resolve(), second.resolve()))
            self.assertNotIn((first / "pose").resolve(), tuple(item.root for item in candidates))

    def test_empty_config_is_reported_but_does_not_hide_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = _make_trial(Path(directory), "空配置")
            config = trial / "config" / "Config.toml"
            config.parent.mkdir()
            config.touch()

            candidate = ExistingResultDiscovery().discover_one(trial)

            self.assertEqual(candidate.config_path, config.resolve())
            self.assertEqual(candidate.config_state, "empty")
            self.assertTrue(candidate.artifacts.pose_2d)


class ExistingResultImporterTests(unittest.TestCase):
    def test_registration_creates_manifest_without_overwriting_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            date_root = Path(directory) / "8.14"
            date_root.mkdir()
            shutil.copy2(FIXTURE_CALIBRATION, date_root / "camera_array.toml")
            trial = _make_trial(date_root, "中文动作", ("cam01", "can02"))
            pose = trial / "pose" / "cam01_json" / "cam01_000000.json"
            original_pose = pose.read_bytes()
            candidate = ExistingResultDiscovery().discover_one(trial)

            project = ExistingResultImporter().register(candidate)

            self.assertTrue((trial / "manifest.json").is_file())
            self.assertEqual(project.root, trial.resolve())
            self.assertEqual(
                [item["camera_id"] for item in project.manifest["cameras"]],
                ["cam01", "can02"],
            )
            self.assertEqual(project.manifest["stages"]["calibration"]["status"], "completed")
            self.assertEqual(project.manifest["stages"]["synchronization"]["status"], "completed")
            self.assertEqual(project.manifest["stages"]["poseEstimation"]["status"], "completed")
            self.assertEqual(project.manifest["stages"]["personAssociation"]["status"], "completed")
            self.assertEqual(project.manifest["stages"]["triangulation"]["status"], "completed")
            self.assertEqual(pose.read_bytes(), original_pose)
            report = json.loads(
                (trial / "reports" / "import" / "artifacts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["pose_2d_files"], 2)
            self.assertFalse(report["has_video"])

    def test_repeated_registration_opens_existing_project_without_rewriting_pose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = _make_trial(Path(directory), "重复登记")
            discovery = ExistingResultDiscovery()
            importer = ExistingResultImporter()
            first = importer.register(discovery.discover_one(trial))
            pose = trial / "pose" / "cam01_json" / "cam01_000000.json"
            before = pose.read_bytes()

            second = importer.register(discovery.discover_one(trial))

            self.assertEqual(first.manifest["project_id"], second.manifest["project_id"])
            self.assertEqual(pose.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
