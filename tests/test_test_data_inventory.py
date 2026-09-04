import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestDataInventoryTests(unittest.TestCase):
    def test_inventory_reports_relative_paths_and_recognized_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文样本"
            (root / "trial" / "pose" / "cam01_json").mkdir(parents=True)
            (root / "camera_array.toml").write_text("[cameras.1]\ncam_id = 1\n", encoding="utf-8")
            (root / "trial" / "pose" / "cam01_json" / "cam01_000001.json").write_text(
                '{"version": 1.3, "people": []}\n', encoding="utf-8"
            )
            (root / "trial" / "pose-3d").mkdir()
            (root / "trial" / "pose-3d" / "sample.trc").write_text("PathFileType\n", encoding="utf-8")
            (root / "trial" / "videos").mkdir()
            (root / "trial" / "videos" / "cam01.mp4").write_bytes(b"video")
            output = Path(directory) / "inventory.json"

            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(Path("scripts/inventory_test_data.ps1").resolve()),
                    "-Root",
                    str(root),
                    "-Output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            payload = json.loads(output.read_text(encoding="utf-8-sig"))
            self.assertEqual(payload["file_count"], 4)
            by_path = {item["relative_path"]: item for item in payload["files"]}
            self.assertEqual(by_path["camera_array.toml"]["format"], "calibration_toml")
            self.assertEqual(
                by_path["trial/pose/cam01_json/cam01_000001.json"]["format"], "pose2d_json"
            )
            self.assertEqual(by_path["trial/pose-3d/sample.trc"]["format"], "pose3d_trc")
            self.assertEqual(by_path["trial/videos/cam01.mp4"]["format"], "video")
            self.assertEqual(by_path["trial/videos/cam01.mp4"]["size"], 5)


if __name__ == "__main__":
    unittest.main()
