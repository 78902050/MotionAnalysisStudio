import json
import tempfile
import unittest
from pathlib import Path

from scripts.real_data_acceptance import run_acceptance


class RealDataAcceptanceScriptTests(unittest.TestCase):
    def test_fixture_acceptance_copies_inputs_and_restores_pose(self) -> None:
        source = Path("tests/fixtures/real_data").resolve()
        pose = source / "pose" / "cam01_json" / "cam01_000000.json"
        original = pose.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "验收输出"
            result = run_acceptance(source, output)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["calibration"]["camera_count"], 4)
            self.assertEqual(result["trajectory"]["frame_count"], 3)
            self.assertEqual(result["pose2d"]["saved_operations"], 1)
            self.assertEqual(result["pose2d"]["restored_operations"], 1)
            self.assertNotIn("poseEstimation", result["correction_rerun_stages"])
            self.assertEqual(pose.read_bytes(), original)
            self.assertEqual(
                json.loads((output / "acceptance.json").read_text(encoding="utf-8"))["status"],
                "passed",
            )

    def test_output_inside_source_is_rejected(self) -> None:
        source = Path("tests/fixtures/real_data").resolve()
        with self.assertRaisesRegex(ValueError, "outside the source"):
            run_acceptance(source, source / "generated-acceptance")


if __name__ == "__main__":
    unittest.main()
