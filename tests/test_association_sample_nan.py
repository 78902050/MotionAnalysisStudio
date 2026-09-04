import json
import tempfile
import unittest
from pathlib import Path

from app.association.analyzer import AssociationAnalyzer
from app.project.manager import ProjectManager
from app.quality.model import QualityReport


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class AssociationSampleNanTests(unittest.TestCase):
    def test_pose2sim_nan_person_is_a_missing_detection_not_a_broken_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "NaN 样本")
            project.manifest["people"] = [{"project_person_id": "person-1"}]
            for layer in ("pose", "pose-sync", "pose-associated"):
                path = project.root / layer / "camA_json" / "camA_000000.json"
                _write_json(
                    path,
                    {"version": 1.3, "people": [{"person_id": [-1], "pose_keypoints_2d": [float("nan")] * 78}]},
                )
            _write_json(
                project.root / "synchronization" / "mapping.json",
                {"offsets": [{"camera": "camA", "frame_delta": 0}]},
            )

            report = AssociationAnalyzer().analyze(project, QualityReport.create("quality-1", {}, (), {}))

            self.assertFalse(any(issue.severity == "blocking" and issue.code == "payload_invalid" for issue in report.issues))

    def test_existing_raw_file_with_missing_person_is_not_a_missing_raw_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory), "缺失人员样本")
            project.manifest["people"] = [{"project_person_id": "person-1"}]
            missing = {"person_id": [-1], "pose_keypoints_2d": [float("nan")] * 78}
            valid = {"keypoints": {"nose": {"x": 1.0, "y": 2.0, "confidence": 0.9}}}
            _write_json(project.root / "pose" / "camA_json" / "camA_000000.json", {"version": 1.3, "people": [missing]})
            _write_json(project.root / "pose-sync" / "camA_json" / "camA_000000.json", {"version": 1.3, "people": [valid]})
            _write_json(project.root / "pose-associated" / "camA_json" / "camA_000000.json", {"version": 1.3, "people": [valid]})
            _write_json(project.root / "synchronization" / "mapping.json", {"offsets": [{"camera": "camA", "frame_delta": 0}]})

            report = AssociationAnalyzer().analyze(project, QualityReport.create("quality-2", {}, (), {}))

            self.assertFalse(any(issue.code == "raw_layer_missing" for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
