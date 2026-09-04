import json
import tempfile
import unittest
from pathlib import Path

from app.association.analyzer import AssociationAnalyzer
from app.association.materializer import AssociationMaterializer
from app.association.overrides import AssociationOverrideStore
from app.project.manager import ProjectManager
from app.quality.model import QualityReport


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _point(x: float, y: float = 20.0) -> dict[str, float]:
    return {"x": x, "y": y, "confidence": 0.9}


def _person(raw_index: int, x: float, project_person_id: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "raw_person_index": raw_index,
        "keypoints": {"nose": _point(x), "left_wrist": _point(x + 5)},
    }
    if project_person_id is not None:
        value["project_person_id"] = project_person_id
    return value


class AssociationTests(unittest.TestCase):
    def _project(self, root: Path) -> ProjectManager:
        project = ProjectManager.create(root, "关联测试")
        project.manifest["people"] = [
            {"project_person_id": "person-left", "display_name": "左侧人物"},
            {"project_person_id": "person-right", "display_name": "右侧人物"},
        ]
        project.manifest["cameras"] = [{"camera_id": "camA"}]
        _write_json(
            root / "synchronization" / "mapping.json",
            {"offsets": [{"camera": "camA", "frame_delta": 0}]},
        )
        _write_json(
            root / "pose" / "camA.json",
            {
                "camera": "camA",
                "keypoint_names": ["nose", "left_wrist"],
                "frames": [
                    {"frame": 0, "people": [_person(0, 10), _person(1, 100)]},
                    {"frame": 1, "people": [_person(0, 11), _person(1, 101)]},
                    {"frame": 2, "people": [_person(0, 12), _person(1, 102)]},
                    {"frame": 3, "people": [_person(0, 13), _person(1, 103)]},
                ],
            },
        )
        _write_json(
            root / "pose-sync" / "camA.json",
            {
                "camera": "camA",
                "keypoint_names": ["nose", "left_wrist"],
                "frames": [
                    # The array order is intentionally different from pose.
                    {"frame": 0, "people": [_person(1, 100), _person(0, 10)]},
                    {"frame": 1, "people": [_person(0, 11), _person(1, 101)]},
                    {"frame": 2, "people": [_person(0, 12), _person(1, 102)]},
                    {"frame": 3, "people": [_person(0, 13), _person(1, 103)]},
                ],
            },
        )
        _write_json(
            root / "pose-associated" / "results.json",
            {
                "frames": [
                    {
                        "camera": "camA",
                        "frame": 0,
                        "people": [
                            _person(1, 100, "person-left"),
                            _person(0, 10, "person-right"),
                        ],
                    },
                    {
                        "camera": "camA",
                        "frame": 1,
                        "people": [
                            _person(0, 11, "person-right"),
                            _person(1, 101, "person-left"),
                        ],
                    },
                    {
                        "camera": "camA",
                        "frame": 2,
                        "people": [_person(0, 12, "person-right")],
                    },
                    {
                        "camera": "camA",
                        "frame": 3,
                        "people": [_person(1, 103, "person-left")],
                    },
                ]
            },
        )
        project.save_manifest()
        return project

    @staticmethod
    def _quality_report() -> QualityReport:
        return QualityReport.create("quality-1", {}, (), {})

    def test_semantic_association_survives_detection_array_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))

            report = AssociationAnalyzer().analyze(project, self._quality_report())

            exact = [candidate for candidate in report.candidates if candidate.exact]
            self.assertTrue(any(item.project_person_id == "person-left" and item.raw_person_index == 1 for item in exact))
            self.assertTrue(any(item.project_person_id == "person-right" and item.raw_person_index == 0 for item in exact))
            self.assertFalse(any("array order" in issue.message.lower() for issue in report.issues))

    def test_missing_mapping_and_missing_layer_are_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            (project.root / "synchronization" / "mapping.json").unlink()
            (project.root / "pose-associated" / "results.json").unlink()

            report = AssociationAnalyzer().analyze(project, self._quality_report())

            self.assertTrue(report.has_blocking_issues)
            messages = " ".join(issue.message for issue in report.issues)
            self.assertIn("mapping", messages.lower())
            self.assertIn("pose-associated", messages)

    def test_bad_payload_and_duplicate_frame_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            _write_json(project.root / "pose-sync" / "camA.json", {"camera": "camA", "frames": "bad"})
            _write_json(
                project.root / "pose-associated" / "results.json",
                {
                    "frames": [
                        {"camera": "camA", "frame": 0, "people": []},
                        {"camera": "camA", "frame": 0, "people": []},
                    ]
                },
            )

            report = AssociationAnalyzer().analyze(project, self._quality_report())

            messages = " ".join(issue.message for issue in report.issues)
            self.assertIn("frames", messages.lower())
            self.assertIn("duplicate", messages.lower())

    def test_ambiguous_candidates_are_not_automatically_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            _write_json(
                project.root / "pose-associated" / "results.json",
                {"frames": [{"camera": "camA", "frame": 1, "people": []}]},
            )

            report = AssociationAnalyzer().analyze(project, self._quality_report())
            candidates = [
                item
                for item in report.candidates
                if item.synchronized_frame == 1 and item.project_person_id == "person-left"
            ]

            self.assertGreaterEqual(len(candidates), 2)
            self.assertTrue(all(not item.exact for item in candidates))
            self.assertTrue(any("multiple" in issue.message.lower() for issue in report.issues))

    def test_override_store_requires_confirmation_and_preserves_unconstrained_people(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            report = AssociationAnalyzer().analyze(project, self._quality_report())
            candidate = next(item for item in report.candidates if item.exact and item.project_person_id == "person-left")
            override = AssociationOverrideStore(project.root).save_confirmed(candidate)
            self.assertEqual(override.project_person_id, "person-left")
            self.assertEqual(AssociationOverrideStore(project.root).effective_constraints(report), (override,))

            result = AssociationMaterializer().materialize(project, (override,))
            self.assertTrue(result.succeeded)
            payload = json.loads((project.root / "pose-associated" / "results.json").read_text(encoding="utf-8"))
            people = payload["frames"][0]["people"]
            self.assertEqual(people[0]["project_person_id"], "person-left")
            self.assertTrue(any("project_person_id" not in item for item in people[1:]))
            self.assertTrue((project.root / "corrections" / "backups" / "association" / "results.json").is_file())

    def test_track_gap_creates_separate_segments_and_materialization_can_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            report = AssociationAnalyzer().analyze(project, self._quality_report())
            left = [item for item in report.candidates if item.exact and item.project_person_id == "person-left"]
            constraints = (
                AssociationOverrideStore(project.root).save_confirmed(left[0]),
                AssociationOverrideStore(project.root).save_confirmed(next(item for item in left if item.synchronized_frame == 3)),
            )
            result = AssociationMaterializer().materialize(project, constraints)

            self.assertGreaterEqual(len(result.track_segments), 2)
            self.assertTrue(AssociationMaterializer().restore(project).succeeded)
            restored = json.loads((project.root / "pose-associated" / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(restored["frames"][0]["people"][0]["project_person_id"], "person-left")


if __name__ == "__main__":
    unittest.main()
