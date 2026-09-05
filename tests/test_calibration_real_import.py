import tempfile
import unittest
from pathlib import Path

from app.calibration.importer import CalibrationImporter
from app.project.manager import ProjectManager


FIXTURE = Path("tests/fixtures/real_data/calibration/camera_array.toml")


class CalibrationRealImportTests(unittest.TestCase):
    def test_real_caliscope_preview_and_activation_expose_parameter_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "真实标定")
            first = root / "first.toml"
            second = root / "second.toml"
            original = FIXTURE.read_text(encoding="utf-8")
            first.write_text(original, encoding="utf-8")
            second.write_text(
                original.replace(
                    "translation = [-0.1755958872933265, 0.32738027414523707, 1.3925009234181136]",
                    "translation = [-0.2755958872933265, 0.32738027414523707, 1.3925009234181136]",
                    1,
                ),
                encoding="utf-8",
            )
            importer = CalibrationImporter()

            preview = importer.preview(project, first)
            self.assertEqual(preview.source_format, "caliscope_toml")
            self.assertEqual(preview.camera_ids, ("1", "2", "3", "4"))
            self.assertFalse(preview.equivalent)
            importer.activate(project, preview)

            changed = importer.preview(project, second)
            self.assertFalse(changed.equivalent)
            self.assertTrue(any("1" in item and "translation" in item for item in changed.differences))
            self.assertTrue(any("→" in item for item in changed.differences))
            result = importer.activate(project, changed)
            self.assertTrue(result.changed)
            self.assertEqual(result.active_path.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))

    def test_semantically_equivalent_toml_does_not_invalidate_or_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "等价标定")
            first = root / "first.toml"
            equivalent = root / "equivalent.toml"
            content = FIXTURE.read_text(encoding="utf-8")
            first.write_text(content, encoding="utf-8")
            equivalent.write_text("# formatting-only change\n" + content, encoding="utf-8")
            importer = CalibrationImporter()
            first_result = importer.import_file(project, first)
            active_before = first_result.active_path.read_bytes()
            generations_before = {
                name: record["generation"] for name, record in project.manifest["stages"].items()
            }

            preview = importer.preview(project, equivalent)
            result = importer.activate(project, preview)

            self.assertTrue(preview.equivalent)
            self.assertFalse(result.changed)
            self.assertEqual(first_result.active_path.read_bytes(), active_before)
            self.assertEqual(
                {name: record["generation"] for name, record in project.manifest["stages"].items()},
                generations_before,
            )

    def test_invalid_matrix_and_non_finite_values_are_rejected_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "非法标定")
            content = FIXTURE.read_text(encoding="utf-8")
            malformed = root / "malformed.toml"
            malformed.write_text(content.replace("matrix = [[", "matrix = [", 1), encoding="utf-8")
            non_finite = root / "non-finite.toml"
            non_finite.write_text(content.replace("1800.7642243824253", "nan", 1), encoding="utf-8")
            invalid_focal = root / "invalid-focal.toml"
            invalid_focal.write_text(content.replace("1800.7642243824253", "-1.0", 1), encoding="utf-8")
            invalid_rotation = root / "invalid-rotation.toml"
            invalid_rotation.write_text(
                content.replace(
                    "rotation = [0.9665559755869323, -1.459692964329389, 1.4673557873492513]",
                    "rotation = [0.0, 1.0]",
                    1,
                ),
                encoding="utf-8",
            )
            importer = CalibrationImporter()

            with self.assertRaises(ValueError):
                importer.preview(project, malformed)
            with self.assertRaisesRegex(ValueError, "finite"):
                importer.preview(project, non_finite)
            with self.assertRaisesRegex(ValueError, "focal"):
                importer.preview(project, invalid_focal)
            with self.assertRaisesRegex(ValueError, "rotation"):
                importer.preview(project, invalid_rotation)
            self.assertNotIn("calibration", project.manifest)

    def test_project_camera_set_mismatch_blocks_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "相机集合")
            project.manifest["cameras"] = [
                {"camera_id": "1"},
                {"camera_id": "2"},
                {"camera_id": "3"},
                {"camera_id": "missing-camera"},
            ]
            project.save_manifest()
            importer = CalibrationImporter()

            preview = importer.preview(project, FIXTURE)

            self.assertTrue(any(issue.severity == "blocking" for issue in preview.issues))
            with self.assertRaisesRegex(ValueError, "相机集合"):
                importer.activate(project, preview)
            self.assertNotIn("calibration", project.manifest)


if __name__ == "__main__":
    unittest.main()
