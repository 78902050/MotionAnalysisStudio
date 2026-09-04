import tempfile
import unittest
from pathlib import Path

from app.correction.rerun import (
    CORRECTION_RERUN_STAGES,
    invalidate_from,
    run_correction_rerun,
)
from app.project.manager import ProjectManager
from app.adapters.pose2sim.runner import RunResult
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore


class _Runner:
    def __init__(
        self,
        *,
        succeeded: bool = True,
        cancelled: bool = False,
        error: str | None = None,
        failed_stage: str | None = None,
        result_project_id: str | None = None,
    ) -> None:
        self.stages = None
        self.succeeded = succeeded
        self.cancelled = cancelled
        self.error = error
        self.failed_stage = failed_stage
        self.result_project_id = result_project_id

    def run(self, request, stages):
        self.stages = tuple(stages)
        return RunResult(
            "task-1",
            self.result_project_id or request.project_id,
            request.generation,
            tuple(stages),
            self.succeeded,
            self.cancelled,
            Path("rerun.log"),
            self.error,
            self.failed_stage,
        )


class CorrectionRerunTests(unittest.TestCase):
    def test_invalidation_preserves_pose_estimation_and_rerun_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "修正重跑")
            for stage in project.manifest["stages"].values():
                stage["status"] = "completed"
            project.save_manifest()

            affected = invalidate_from(project, "personAssociation", "2D correction", "op-1")

            self.assertEqual(affected, list(CORRECTION_RERUN_STAGES))
            self.assertEqual(project.manifest["stages"]["poseEstimation"]["status"], "completed")
            self.assertNotIn("poseEstimation", CORRECTION_RERUN_STAGES)

            runner = _Runner()
            result = run_correction_rerun(project, "session-1", runner)
            self.assertTrue(result.succeeded)
            self.assertEqual(runner.stages, CORRECTION_RERUN_STAGES)
            self.assertNotIn("poseEstimation", runner.stages)
            self.assertTrue(all(
                project.manifest["stages"][stage]["status"] == "completed"
                for stage in CORRECTION_RERUN_STAGES
            ))

    def test_successful_rerun_versions_quality_report_with_distinct_before_and_after(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "质量版本")
            before = QualityReport.create("quality-before", {"missing_rate": 0.2}, (), {})
            QualityReportStore(project).save(before)

            result = run_correction_rerun(project, "session-1", _Runner())
            current = QualityReportStore(project).load_current()
            quality_state = project.manifest["quality"]

            self.assertTrue(result.succeeded)
            self.assertNotEqual(current.report_id, before.report_id)
            self.assertEqual(quality_state["comparison"]["before_report_id"], before.report_id)
            self.assertEqual(quality_state["comparison"]["after_report_id"], current.report_id)
            self.assertNotEqual(
                quality_state["comparison"]["before_report_id"],
                quality_state["comparison"]["after_report_id"],
            )

    def test_failed_rerun_preserves_current_report_and_marks_it_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "失败保护")
            before = QualityReport.create("quality-before", {"missing_rate": 0.2}, (), {})
            QualityReportStore(project).save(before)
            current_path = project.path_for("quality_report")
            before_bytes = current_path.read_bytes()
            runner = _Runner(
                succeeded=False,
                error="stage filtering exited with code 1",
                failed_stage="filtering",
            )

            result = run_correction_rerun(project, "session-1", runner)

            self.assertFalse(result.succeeded)
            self.assertEqual(current_path.read_bytes(), before_bytes)
            self.assertEqual(project.manifest["quality"]["status"], "stale")
            self.assertEqual(project.manifest["quality"]["failed_stage"], "filtering")
            self.assertEqual(project.manifest["quality"]["log_path"], "rerun.log")
            self.assertEqual(QualityReportStore(project).load_current().report_id, "quality-before")

    def test_cancelled_rerun_preserves_report_and_restores_pending_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "取消保护")
            before = QualityReport.create("quality-before", {"missing_rate": 0.2}, (), {})
            QualityReportStore(project).save(before)
            current_path = project.path_for("quality_report")
            before_bytes = current_path.read_bytes()

            result = run_correction_rerun(
                project,
                "session-1",
                _Runner(succeeded=False, cancelled=True, failed_stage="personAssociation"),
            )

            self.assertTrue(result.cancelled)
            self.assertEqual(current_path.read_bytes(), before_bytes)
            self.assertEqual(project.manifest["quality"]["status"], "stale")
            self.assertTrue(
                all(
                    project.manifest["stages"][stage]["status"] == "pending"
                    for stage in CORRECTION_RERUN_STAGES
                )
            )

    def test_foreign_task_result_cannot_replace_current_project_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "项目隔离")
            before = QualityReport.create("quality-before", {"missing_rate": 0.2}, (), {})
            QualityReportStore(project).save(before)
            current_path = project.path_for("quality_report")
            before_bytes = current_path.read_bytes()

            run_correction_rerun(
                project,
                "session-1",
                _Runner(result_project_id="another-project"),
            )

            self.assertEqual(current_path.read_bytes(), before_bytes)
            self.assertEqual(project.manifest["quality"]["status"], "stale")
            self.assertEqual(
                QualityReportStore(project).load_current().report_id, before.report_id
            )


if __name__ == "__main__":
    unittest.main()
