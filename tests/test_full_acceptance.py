import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.analysis.comparison import ComparisonMember, ComparisonRequest, ComparisonService
from app.analysis.cycles import CycleBuilder, CycleDefinition
from app.analysis.events import EventDetector, EventRule
from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, Trajectory
from app.application.controller import ApplicationController
from app.application.quality_correction_service import QualityCorrectionService
from app.calibration.importer import CalibrationImporter
from app.correction.history import CorrectionHistory
from app.correction.rerun import CORRECTION_RERUN_STAGES
from app.domain.addresses import FrameAddress, KeypointAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore


class FullAcceptanceTests(unittest.TestCase):
    def test_quality_correction_analysis_and_report_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "中文验收项目"
            project = ProjectManager.create(root, "完整验收")
            CalibrationImporter().import_file(
                project,
                Path("tests/fixtures/real_data/calibration/camera_array.toml"),
            )
            project.manifest["cameras"] = [{"camera_id": "cam01"}]
            project.manifest["people"] = [{"project_person_id": "person-01"}]
            project.save_manifest()
            shutil.copytree(
                Path("tests/fixtures/real_data/pose"),
                root / "pose",
                dirs_exist_ok=True,
            )
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps({"offsets": [{"camera": "cam01", "frame_delta": 0, "source": "acceptance"}]}),
                encoding="utf-8",
            )
            (root / "pose-associated" / "results.json").write_text(
                json.dumps(
                    {
                        "frames": [
                            {
                                "camera": "cam01",
                                "frame": 0,
                                "people": [{"project_person_id": "person-01", "raw_person_index": 0}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            issue = QualityIssue(
                "acceptance-issue",
                "reprojection",
                "warning",
                FrameAddress("cam01", "pose2d", 0),
                PersonAddress("person-01"),
                KeypointAddress("halpe26", "nose", 0),
                "验收点位",
            )
            QualityReportStore(project).save(
                QualityReport.create("quality-before", {"mean_error": 1.0}, (issue,), {"pose": "fixture-v1"})
            )

            service = QualityCorrectionService(project)
            resolution = service.resolve_issue(issue)
            self.assertTrue(resolution.can_edit, resolution.blocker)
            assert resolution.edit_target is not None and resolution.pose_path is not None
            session = service.create_session(resolution)
            before = session.document.value_at(resolution.edit_target)
            session.apply_point(resolution.edit_target, before[0] + 1.0, before[1] + 2.0)
            session.undo()
            self.assertEqual(session.document.value_at(resolution.edit_target), before)
            session.redo()
            saved, operation_ids = session.save(note="完整验收")
            self.assertEqual(saved, 1)
            self.assertEqual(len(operation_ids), 1)
            history = CorrectionHistory(root)
            self.assertTrue(history.backup_path(resolution.pose_path).is_file())
            self.assertEqual(history.restore_file(resolution.pose_path, "验收恢复"), 1)
            self.assertEqual(service._document(resolution.pose_path, resolution.keypoint_names).value_at(resolution.edit_target), before)

            self.assertNotIn("poseEstimation", CORRECTION_RERUN_STAGES)
            self.assertEqual(CORRECTION_RERUN_STAGES[0], "personAssociation")

            trajectory = Trajectory(
                (0, 1, 2),
                (0.0, 1.0, 2.0),
                {"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (4.0, 0.0, 0.0))},
                "m",
                "world",
                "fixture.trc",
                "trajectory-v1",
                {"sampling_rate_hz": 1.0},
            )
            metrics = MetricEngine().calculate(
                trajectory,
                (MetricDefinition("speed:hip", "m/s", ("hip",)),),
                MetricConfig(1.0, "m", None),
            )
            start = EventDetector().detect(
                metrics,
                EventRule("speed-start", "hip.speed", "crosses_above", 1.5, role="start"),
            )
            end = EventDetector().detect(
                metrics,
                EventRule("speed-end", "hip.speed", "crosses_above", 2.5, role="end"),
            )
            cycles = CycleBuilder().build(
                start + end,
                CycleDefinition("acceleration-phase", "speed-start", "speed-end"),
            )
            self.assertEqual(len(cycles), 1)

            member = ComparisonMember("acceptance", "person-01", "trial-01", metrics, start + end)
            comparison = ComparisonService((member,))
            report = comparison.build(
                ComparisonRequest(("acceptance",), ("person-01",), ("trial-01",), "frame")
            )
            output = root / "reports" / "comparisons" / f"{report.report_id}.csv"
            comparison.export(report, output, "csv")
            self.assertIn("unit", output.read_text(encoding="utf-8").splitlines()[0])

            controller = ApplicationController()
            self.assertTrue(controller.open_project(project))
            self.assertTrue(controller.shutdown(dirty_decision="discard"))
            self.assertTrue(controller.supervisor.wait_for_shutdown(1000))

    def test_corrupt_pose_is_visible_and_does_not_replace_the_last_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "故障注入")
            pose = project.root / "pose" / "cam01_json" / "cam01_000000.json"
            pose.parent.mkdir(parents=True, exist_ok=True)
            readable = b'{"version": 1.3, "people": []}'
            pose.write_bytes(readable)
            backup = project.root / "corrections" / "backups" / "pose" / "cam01_json" / pose.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(readable)
            pose.write_text('{"broken":', encoding="utf-8")

            with self.assertRaises((ValueError, json.JSONDecodeError)):
                json.loads(pose.read_text(encoding="utf-8"))

            self.assertEqual(backup.read_bytes(), readable)


if __name__ == "__main__":
    unittest.main()
