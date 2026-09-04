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


class _Runner:
    def __init__(self) -> None:
        self.stages = None

    def run(self, request, stages):
        self.stages = tuple(stages)
        return RunResult(
            "task-1",
            request.project_id,
            request.generation,
            tuple(stages),
            True,
            False,
            Path("rerun.log"),
        )


class CorrectionRerunTests(unittest.TestCase):
    def test_invalidation_preserves_pose_estimation_and_rerun_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "修正重跑")
            for stage in project.manifest["stages"].values():
                stage["status"] = "completed"
            project.save_manifest()

            affected = invalidate_from(project, "triangulation", "2D correction", "op-1")

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


if __name__ == "__main__":
    unittest.main()
