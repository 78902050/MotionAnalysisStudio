import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.calibration.importer import CalibrationImporter
from app.project.manager import ProjectManager


def _calibration(camera_ids: list[str]) -> dict[str, object]:
    return {
        "cameras": [
            {
                "camera_id": camera_id,
                "intrinsics": {"fx": 1000.0, "fy": 1000.0},
                "extrinsics": {"rotation": [1, 0, 0], "translation": [0, 0, 0]},
            }
            for camera_id in camera_ids
        ]
    }


class CalibrationImportTests(unittest.TestCase):
    def test_changed_content_updates_active_file_and_same_content_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "标定测试")
            source = root / "标定文件.json"
            source.write_text(json.dumps(_calibration(["cam01"])), encoding="utf-8")
            importer = CalibrationImporter()

            first = importer.import_file(project, source)
            source.write_text(json.dumps(_calibration(["cam01", "cam02"])), encoding="utf-8")
            second = importer.import_file(project, source)
            third = importer.import_file(project, source)

            self.assertTrue(first.changed)
            self.assertTrue(second.changed)
            self.assertFalse(third.changed)
            self.assertEqual(first.active_path, second.active_path)
            self.assertEqual(project.manifest["calibration"]["active_path"], str(second.active_path.relative_to(root / "project")))
            self.assertEqual(project.manifest["calibration"]["camera_ids"], ["cam01", "cam02"])
            self.assertEqual(json.loads(second.active_path.read_text(encoding="utf-8")), _calibration(["cam01", "cam02"]))

    def test_corrupt_source_and_unwritable_destination_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "标定测试")
            source = root / "bad.json"
            source.write_text("{broken", encoding="utf-8")
            importer = CalibrationImporter()

            with self.assertRaises(ValueError):
                importer.inspect(source)

            source.write_text(json.dumps(_calibration(["cam01"])), encoding="utf-8")
            with patch("app.calibration.importer.os.replace", side_effect=OSError("read-only")):
                with self.assertRaises(OSError):
                    importer.import_file(project, source)

            self.assertNotIn("calibration", project.manifest)


if __name__ == "__main__":
    unittest.main()
