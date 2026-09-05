import tempfile
import unittest
from pathlib import Path

from app.analysis.comparison import ComparisonMember, ComparisonRequest, ComparisonService
from app.analysis.contracts import MetricSeriesContract
from app.analysis.cycles import CycleBuilder, CycleDefinition
from app.analysis.event_history import EventHistory
from app.analysis.events import Event, EventDetector, EventRule
from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, MetricTable, Trajectory


def _trajectory(
    points: dict[str, tuple[tuple[float, float, float], ...]],
    *,
    times: tuple[float, ...] = (0.0, 1.0, 2.0),
    sampling_rate_hz: float = 1.0,
) -> Trajectory:
    return Trajectory(
        tuple(range(len(times))),
        times,
        points,
        "m",
        "world",
        "fixture.trc",
        "artifact-v1",
        {"sampling_rate_hz": sampling_rate_hz},
    )


def _table(
    *,
    unit: str = "m/s",
    coordinate_system: str = "world",
    algorithm_version: str = "kinematics-v2",
    input_version: str = "input-v1",
) -> MetricTable:
    contract = MetricSeriesContract(
        "speed",
        unit,
        "m",
        coordinate_system,
        algorithm_version,
        "seconds",
    )
    return MetricTable(
        (0, 1, 2),
        (0.0, 1.0, 2.0),
        {"hip.speed": (0.0, 1.0, 2.0)},
        {"hip.speed": unit},
        {
            "coordinate_system": coordinate_system,
            "coordinate_unit": "m",
            "sampling_rate_hz": 1.0,
            "input_version": input_version,
        },
        {"hip.speed": {"metric_id": "speed:hip", "input_version": input_version}},
        {"hip.speed": contract},
    )


class AnalysisContractTests(unittest.TestCase):
    def test_metric_units_are_constrained_by_metric_kind(self) -> None:
        trajectory = _trajectory({"hip": ((0.0, 0.0, 0.0),) * 3})
        invalid = (
            MetricDefinition("speed:hip", "deg", ("hip",)),
            MetricDefinition("acceleration:hip", "m/s", ("hip",)),
            MetricDefinition("angle:hip:hip:hip", "m", ("hip", "hip", "hip")),
        )

        for definition in invalid:
            with self.subTest(definition=definition.metric_id, unit=definition.unit):
                with self.assertRaisesRegex(ValueError, "unit"):
                    MetricEngine().calculate(trajectory, (definition,), MetricConfig(1.0, "m", None))

    def test_sampling_rate_must_agree_with_real_timeline(self) -> None:
        trajectory = _trajectory(
            {"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))},
            times=(0.0, 0.2, 0.4),
            sampling_rate_hz=10.0,
        )

        with self.assertRaisesRegex(ValueError, "sampling rate.*timeline"):
            MetricEngine().calculate(
                trajectory,
                (MetricDefinition("speed:hip", "m/s", ("hip",)),),
                MetricConfig(10.0, "m", None),
            )

    def test_local_symmetry_is_invariant_to_coordinate_origin_translation(self) -> None:
        points = {
            "left": ((-2.0, 0.0, 0.0), (-3.0, 0.0, 0.0), (-4.0, 0.0, 0.0)),
            "right": ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)),
            "midline": ((0.0, 0.0, 0.0),) * 3,
        }
        moved = {
            name: tuple((x + 1000.0, y - 400.0, z + 20.0) for x, y, z in series)
            for name, series in points.items()
        }
        definition = MetricDefinition("symmetry:left:right:midline", "m", ("left", "right", "midline"))

        first = MetricEngine().calculate(_trajectory(points), (definition,), MetricConfig(1.0, "m", None))
        second = MetricEngine().calculate(_trajectory(moved), (definition,), MetricConfig(1.0, "m", None))

        column = "symmetry.left.right.midline"
        self.assertEqual(first.column(column), second.column(column))

    def test_comparison_rejects_incompatible_units_coordinates_and_algorithms(self) -> None:
        baseline = ComparisonMember("p1", "person", "trial", _table())
        variants = (
            ComparisonMember("p2", "person", "trial", _table(unit="cm/s")),
            ComparisonMember("p2", "person", "trial", _table(coordinate_system="camera")),
            ComparisonMember("p2", "person", "trial", _table(algorithm_version="kinematics-v3")),
        )
        request = ComparisonRequest(("p1", "p2"), ("person",), ("trial",), "frame")

        for variant in variants:
            with self.subTest(contract=variant.metrics.contract("hip.speed")):
                with self.assertRaisesRegex(ValueError, "incompatible metric contract"):
                    ComparisonService((baseline, variant)).build(request)

    def test_cycle_definition_pairs_different_start_and_end_rules(self) -> None:
        events = (
            Event("contact-1", "contact", "start", 1, 0.1, 1.0, "segment-0"),
            Event("toeoff-1", "toeoff", "end", 5, 0.5, 1.0, "segment-0"),
        )
        definition = CycleDefinition("stance", "contact", "toeoff")

        cycles = CycleBuilder().build(events, definition)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].rule_id, "stance")
        self.assertEqual((cycles[0].start_frame, cycles[0].end_frame), (1, 5))

    def test_manual_event_remains_visible_when_detector_version_changes(self) -> None:
        metrics = _table()
        old_event = EventDetector("detector-v1").detect(
            metrics, EventRule("contact", "hip.speed", "crosses_above", 0.5)
        )[0]
        manual = Event(
            old_event.event_id,
            old_event.rule_id,
            old_event.role,
            2,
            2.0,
            2.0,
            old_event.segment_id,
            "manual",
            "人工确认",
            old_event.detector_version,
        )
        new_event = EventDetector("detector-v2").detect(
            metrics, EventRule("contact", "hip.speed", "crosses_above", 1.5)
        )[0]
        with tempfile.TemporaryDirectory() as directory:
            history = EventHistory(Path(directory) / "events.jsonl")
            history.append(old_event)
            history.append_manual(manual)

            effective = history.effective_events((new_event,))

        self.assertEqual(len(effective), 1)
        self.assertEqual(effective[0].source, "manual")
        self.assertEqual(effective[0].frame, 2)

    def test_report_id_and_exported_rows_include_artifact_version_and_unit(self) -> None:
        request = ComparisonRequest(("project",), ("person",), ("trial",), "frame")
        first_service = ComparisonService((ComparisonMember("project", "person", "trial", _table(input_version="v1")),))
        second_service = ComparisonService((ComparisonMember("project", "person", "trial", _table(input_version="v2")),))

        first = first_service.build(request)
        second = second_service.build(request)

        self.assertNotEqual(first.report_id, second.report_id)
        self.assertEqual(first.rows[0].unit, "m/s")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            first_service.export(first, path, "csv")
            self.assertIn("unit", path.read_text(encoding="utf-8").splitlines()[0])

    def test_trc_malformed_row_reports_the_exact_line(self) -> None:
        content = "\n".join(
            (
                "PathFileType\t4\t(X/Y/Z)\tbroken.trc",
                "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
                "60\t60\t1\t1\tm\t60\t1\t1",
                "Frame#\tTime\tHip\t",
                "\t\tX1\tY1\tZ1",
                "1\t0.0\tbad\t2.0\t3.0",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.trc"
            path.write_text(content, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 6"):
                Trajectory.from_trc(path, "world")


if __name__ == "__main__":
    unittest.main()
