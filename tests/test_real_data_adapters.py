import importlib
import importlib.util
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from app.analysis.model import Trajectory


FIXTURES = Path("tests/fixtures/real_data")
KEYPOINT_NAMES = tuple(f"kp{index:02d}" for index in range(26))


class RealDataAdapterTests(unittest.TestCase):
    def _calibration_repository_type(self):
        module_name = "app.adapters.caliscope.calibration_repository"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "real Caliscope TOML repository is not implemented",
        )
        return importlib.import_module(module_name).CaliscopeCalibrationRepository

    def _pose_repository_type(self):
        module_name = "app.adapters.pose2sim.pose2d_repository"
        self.assertIsNotNone(
            importlib.util.find_spec(module_name),
            "real Pose2Sim frame repository is not implemented",
        )
        return importlib.import_module(module_name).Pose2DRepository

    def test_reads_real_caliscope_and_aniposelib_toml(self) -> None:
        repository_type = self._calibration_repository_type()
        repository = repository_type()

        caliscope = repository.load(FIXTURES / "calibration" / "camera_array.toml")
        aniposelib = repository.load(
            FIXTURES / "calibration" / "camera_array_aniposelib.toml"
        )

        self.assertEqual(caliscope.source_format, "caliscope_toml")
        self.assertEqual(tuple(camera.camera for camera in caliscope.cameras), ("1", "2", "3", "4"))
        self.assertEqual(caliscope.cameras[0].image_size, (3840, 2160))
        self.assertEqual(len(caliscope.cameras[0].matrix), 3)
        self.assertAlmostEqual(caliscope.cameras[0].reprojection_error, 0.4235838221894082)
        self.assertEqual(aniposelib.source_format, "aniposelib_toml")
        self.assertEqual(tuple(camera.camera for camera in aniposelib.cameras), ("cam_1", "cam_2", "cam_3", "cam_4"))

    def test_empty_real_calibration_is_rejected(self) -> None:
        repository_type = self._calibration_repository_type()

        with self.assertRaisesRegex(ValueError, "no cameras"):
            repository_type().load(FIXTURES / "calibration" / "camera_array_empty.toml")

    def test_loads_real_pose2sim_frame_with_explicit_keypoint_names(self) -> None:
        repository_type = self._pose_repository_type()
        document = repository_type(FIXTURES / "pose", KEYPOINT_NAMES).load_frame("cam01", 0)
        frame = document.frame_pose()

        self.assertEqual(frame.camera, "cam01")
        self.assertEqual(frame.frame, 0)
        self.assertEqual(len(frame.people), 2)
        self.assertEqual(len(frame.people[0].keypoints), 26)
        point = frame.people[0].keypoints[0]
        self.assertEqual(point.name, "kp00")
        self.assertAlmostEqual(point.x, 1986.337999343872)
        self.assertAlmostEqual(point.confidence, 0.7194989919662476)

    def test_pose_update_preserves_other_people_and_unknown_fields(self) -> None:
        repository_type = self._pose_repository_type()
        with tempfile.TemporaryDirectory() as directory:
            pose_root = Path(directory) / "pose"
            shutil.copytree(FIXTURES / "pose", pose_root)
            path = pose_root / "cam01_json" / "cam01_000000.json"
            before = json.loads(path.read_text(encoding="utf-8"))
            document = repository_type(pose_root, KEYPOINT_NAMES).load_frame("cam01", 0)

            old = document.set_point(0, "kp00", (10.0, 20.0, 1.0))
            document.save()

            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                old,
                (1986.337999343872, 1017.1509076356888, 0.7194989919662476),
            )
            self.assertEqual(after["version"], before["version"])
            self.assertEqual(after["people"][1], before["people"][1])
            self.assertEqual(after["people"][0]["person_id"], before["people"][0]["person_id"])
            self.assertEqual(after["people"][0]["face_keypoints_2d"], [])
            self.assertEqual(after["people"][0]["pose_keypoints_2d"][:3], [10.0, 20.0, 1.0])
            self.assertEqual(
                after["people"][0]["pose_keypoints_2d"][3:],
                before["people"][0]["pose_keypoints_2d"][3:],
            )

    def test_pose_keypoint_name_count_must_match_real_array(self) -> None:
        repository_type = self._pose_repository_type()
        repository = repository_type(FIXTURES / "pose", KEYPOINT_NAMES[:-1])

        with self.assertRaisesRegex(ValueError, "keypoint name count"):
            repository.load_frame("cam01", 0)

    def test_pose_update_preserves_existing_nan_missing_values(self) -> None:
        repository_type = self._pose_repository_type()
        with tempfile.TemporaryDirectory() as directory:
            pose_root = Path(directory) / "pose"
            camera_root = pose_root / "cam01_json"
            camera_root.mkdir(parents=True)
            path = camera_root / "cam01_000000.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1.3,
                        "people": [
                            {
                                "person_id": [-1],
                                "pose_keypoints_2d": [1.0, 2.0, 0.5, math.nan, math.nan, 0.0],
                            }
                        ],
                    },
                    allow_nan=True,
                ),
                encoding="utf-8",
            )
            document = repository_type(pose_root, ("first", "missing")).load_frame("cam01", 0)

            document.set_point(0, "first", (10.0, 20.0, 1.0))
            document.save()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["people"][0]["pose_keypoints_2d"][:3], [10.0, 20.0, 1.0])
            self.assertTrue(math.isnan(payload["people"][0]["pose_keypoints_2d"][3]))

    def test_trimmed_real_trc_preserves_declared_metadata(self) -> None:
        trajectory = Trajectory.from_trc(
            FIXTURES / "pose3d" / "three_frames_65_markers.trc",
            coordinate_system="world",
        )

        self.assertEqual(len(trajectory.frames), 3)
        self.assertEqual(len(trajectory.labels), 65)
        self.assertEqual(trajectory.coordinate_unit, "m")
        self.assertEqual(trajectory.metadata["sampling_rate_hz"], 60.0)
        self.assertAlmostEqual(trajectory.times[0], 1.0 / 60.0)


if __name__ == "__main__":
    unittest.main()
