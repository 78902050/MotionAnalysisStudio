import json
import tempfile
import unittest
from pathlib import Path

from app.project.manager import ProjectManager
from app.synchronization.analyzer import SynchronizationAnalyzer


class SynchronizationSampleMappingTests(unittest.TestCase):
    def test_pose_layer_file_ranges_are_candidates_until_human_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "样本同步")
            for frame in range(3):
                path = project.root / "pose" / "camA_json" / f"camA_{frame:06d}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"version": 1.3, "people": []}), encoding="utf-8")
            for frame in range(2, 5):
                path = project.root / "pose-sync" / "camA_json" / f"camA_{frame:06d}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"version": 1.3, "people": []}), encoding="utf-8")

            analyzer = SynchronizationAnalyzer()
            report = analyzer.analyze(project)

            self.assertFalse(any(issue.severity == "blocking" for issue in report.issues))
            self.assertEqual(report.trust_by_camera["camA"], "filename_candidate")
            self.assertTrue(any("文件名" in issue.message for issue in report.issues))
            with self.assertRaises(KeyError):
                analyzer.mapping("camA", 2)


if __name__ == "__main__":
    unittest.main()
