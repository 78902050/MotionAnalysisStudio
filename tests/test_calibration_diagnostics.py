import json
import tempfile
import unittest
from pathlib import Path

from app.calibration.diagnostics import CalibrationDiagnostics
from app.calibration.importer import CalibrationImporter
from app.project.manager import ProjectManager


class CalibrationDiagnosticsTests(unittest.TestCase):
    def test_missing_project_camera_is_a_blocking_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root / "project", "标定诊断")
            project.manifest["cameras"] = [
                {"camera_id": "cam01", "display_name": "左前"},
                {"camera_id": "cam02", "display_name": "右前"},
            ]
            project.save_manifest()
            source = root / "calibration.json"
            source.write_text(
                json.dumps(
                    {
                        "cameras": [
                            {
                                "camera_id": "cam01",
                                "reprojection_error": 0.8,
                                "coverage": 0.92,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            CalibrationImporter().import_file(project, source)

            report = CalibrationDiagnostics().analyze(project)

            self.assertEqual(report.active_path, project.root / "calibration" / "source" / source.name)
            self.assertEqual(report.camera_ids, ("cam01",))
            self.assertTrue(any(issue.severity == "blocking" and "cam02" in issue.message for issue in report.issues))

    def test_no_active_calibration_is_explicitly_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "缺失标定")

            report = CalibrationDiagnostics().analyze(project)

            self.assertTrue(any(issue.severity == "blocking" for issue in report.issues))
            self.assertIn("激活", " ".join(issue.message for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
