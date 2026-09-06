import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.pages.association_page import AssociationPage
from app.project.manager import ProjectManager
from app.quality.audit import QualityAuditService
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore


TRC_WITH_ONE_MISSING_POINT = """PathFileType\t4\t(X/Y/Z)\ttrial.trc
DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames
60\t60\t2\t2\tm\t60\t1\t2
Frame#\tTime\tHip\t\t\tKnee\t\t
\t\tX1\tY1\tZ1\tX2\tY2\tZ2
1\t0.000000\t1\t2\t3\t4\t5\t6
2\t0.016667\t7\t8\t9\t\t11\t12
"""


class ExistingQualityAndAssociationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_quality_audit_uses_trc_when_internal_pose3d_json_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "TRC质检", "TRC质检")
            trc = project.root / "pose-3d" / "trial.trc"
            trc.write_text(TRC_WITH_ONE_MISSING_POINT, encoding="utf-8")

            report = QualityAuditService().analyze(project)
            metrics = report.metrics()
            messages = [issue.message for issue in report.issues()]

            self.assertEqual(metrics["3d_total_points"], 4)
            self.assertEqual(metrics["3d_valid_points"], 3)
            self.assertEqual(metrics["3d_missing_points"], 1)
            self.assertEqual(metrics["coverage_start_frame"], 1)
            self.assertEqual(metrics["coverage_end_frame"], 2)
            self.assertFalse(
                any("missing quality input layer: pose-3d" in message for message in messages)
            )

    def test_standard_pose_layers_are_not_reported_as_missing_private_json_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "标准目录", "标准目录")
            payload = json.dumps({"version": 1.3, "people": []})
            for layer in ("pose", "pose-sync", "pose-associated"):
                pose = project.root / layer / "cam01_json" / "cam01_000001.json"
                pose.parent.mkdir(parents=True, exist_ok=True)
                pose.write_text(payload, encoding="utf-8")
            (project.root / "pose-3d" / "trial.trc").write_text(
                TRC_WITH_ONE_MISSING_POINT,
                encoding="utf-8",
            )

            report = QualityAuditService().analyze(project)
            messages = [issue.message for issue in report.issues()]

            self.assertFalse(
                any("missing quality input layer: synchronization" in message for message in messages)
            )
            self.assertFalse(
                any("missing quality input layer: pose-associated" in message for message in messages)
            )
            self.assertTrue(report.inputs["synchronization"]["available"])
            self.assertTrue(report.inputs["association"]["available"])

    def test_association_page_shows_existing_associated_frame_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "已有关联", "已有关联")
            pose = project.root / "pose-associated" / "cam01_json"
            pose.mkdir(parents=True, exist_ok=True)
            for frame in (1, 2, 5):
                (pose / f"cam01_{frame:06d}.json").write_text(
                    json.dumps({"version": 1.3, "people": []}),
                    encoding="utf-8",
                )
            page = AssociationPage()

            page.set_project(project)

            self.assertEqual(page.existing_results_table.rowCount(), 1)
            self.assertEqual(page.existing_results_table.item(0, 0).text(), "cam01")
            self.assertEqual(page.existing_results_table.item(0, 1).text(), "3")
            self.assertEqual(page.existing_results_table.item(0, 2).text(), "1–5")
            self.assertIn("3", page.status.text())
            page.close()

    def test_old_quality_report_without_trc_metrics_is_refreshed_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "旧质检", "旧质检")
            project.manifest["imported_artifacts"] = {"pose_2d_files": 1}
            project.save_manifest()
            pose = project.root / "pose" / "cam01_json" / "cam01_000001.json"
            pose.parent.mkdir(parents=True, exist_ok=True)
            pose.write_text(json.dumps({"version": 1.3, "people": []}), encoding="utf-8")
            (project.root / "pose-3d" / "trial.trc").write_text(
                TRC_WITH_ONE_MISSING_POINT,
                encoding="utf-8",
            )
            QualityReportStore(project).save(
                QualityReport.create("old-report", {"missing_rate": None}, (), {})
            )
            window = MainWindow()
            try:
                self.assertTrue(window.open_project(project))

                self.assertIsNotNone(window.initial_quality_handle)
                self.assertIn("正在后台", window.statusBar().currentMessage())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
