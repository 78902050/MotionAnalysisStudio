import math
import tempfile
import unittest
from pathlib import Path

from app.analysis.coordinates import convert_points
from app.analysis.filters import filter_values
from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, Trajectory


class MetricTests(unittest.TestCase):
    @staticmethod
    def _trajectory(points: dict[str, tuple[tuple[float, float, float], ...]], times: tuple[float, ...] | None = None) -> Trajectory:
        return Trajectory(
            frames=tuple(range(len(next(iter(points.values()))))),
            times=times or tuple(float(index) for index in range(len(next(iter(points.values()))))),
            points=points,
            coordinate_unit="m",
            coordinate_system="world",
            source_path="fixture.trc",
            source_version="fixture-v1",
        )

    def test_coordinate_conversion_requires_explicit_units_and_preserves_axes(self) -> None:
        converted = convert_points(((1.0, -2.0, 0.5),), "m", "mm")
        self.assertEqual(converted, ((1000.0, -2000.0, 500.0),))
        with self.assertRaises(ValueError):
            convert_points(((1.0, 2.0, 3.0),), "m", "yards")

    def test_finite_difference_reports_position_speed_and_acceleration_with_traceability(self) -> None:
        trajectory = self._trajectory(
            {"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (4.0, 0.0, 0.0))},
            times=(0.0, 1.0, 2.0),
        )
        definitions = (
            MetricDefinition("position:hip", "m", ("hip",)),
            MetricDefinition("speed:hip", "m/s", ("hip",)),
            MetricDefinition("acceleration:hip", "m/s^2", ("hip",)),
        )

        table = MetricEngine().calculate(trajectory, definitions, MetricConfig(1.0, "m", None))

        self.assertEqual(table.column("hip.x"), (0.0, 1.0, 4.0))
        self.assertEqual(table.column("hip.speed"), (1.0, 2.0, 3.0))
        self.assertEqual(table.column("hip.acceleration"), (1.0, 1.0, 1.0))
        self.assertEqual(table.units["hip.speed"], "m/s")
        self.assertEqual(table.metadata["coordinate_system"], "world")
        self.assertEqual(table.provenance["hip.speed"]["input_labels"], ("hip",))
        self.assertEqual(table.provenance["hip.speed"]["sampling_rate_hz"], 1.0)

    def test_gap_isolation_does_not_connect_finite_segments(self) -> None:
        nan = float("nan")
        trajectory = self._trajectory(
            {"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (nan, nan, nan), (3.0, 0.0, 0.0), (4.0, 0.0, 0.0))}
        )
        table = MetricEngine().calculate(
            trajectory,
            (MetricDefinition("speed:hip", "m/s", ("hip",)),),
            MetricConfig(1.0, "m", None),
        )

        self.assertEqual(table.column("hip.speed")[:2], (1.0, 1.0))
        self.assertTrue(math.isnan(table.column("hip.speed")[2]))
        self.assertEqual(table.column("hip.speed")[3:], (1.0, 1.0))

    def test_filter_does_not_average_across_missing_gap(self) -> None:
        values = (0.0, 2.0, float("nan"), 4.0, 6.0)

        filtered = filter_values(values, "moving_average", window=3)

        self.assertEqual(filtered[:2], (1.0, 1.0))
        self.assertTrue(math.isnan(filtered[2]))
        self.assertEqual(filtered[3:], (5.0, 5.0))

    def test_angle_and_angular_velocity_use_declared_units(self) -> None:
        trajectory = self._trajectory(
            {
                "hip": ((0.0, 0.0, 0.0),) * 3,
                "shoulder": ((1.0, 0.0, 0.0),) * 3,
                "elbow": ((1.0, 0.5, 0.0), (1.0, 1.0, 0.0), (1.0, 1.5, 0.0)),
            }
        )
        definitions = (
            MetricDefinition("angle:hip:shoulder:elbow", "deg", ("hip", "shoulder", "elbow")),
            MetricDefinition("angular_velocity:hip:shoulder:elbow", "deg/s", ("hip", "shoulder", "elbow")),
        )

        table = MetricEngine().calculate(trajectory, definitions, MetricConfig(1.0, "m", None))

        self.assertAlmostEqual(table.column("angle.hip.shoulder.elbow")[1], 90.0)
        self.assertEqual(table.units["angular_velocity.hip.shoulder.elbow"], "deg/s")
        self.assertTrue(all(math.isfinite(value) for value in table.column("angular_velocity.hip.shoulder.elbow")))

    def test_missing_required_label_propagates_missing_values(self) -> None:
        trajectory = self._trajectory({"hip": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))})

        table = MetricEngine().calculate(
            trajectory,
            (MetricDefinition("speed:knee", "m/s", ("knee",)),),
            MetricConfig(1.0, "m", None),
        )

        self.assertTrue(all(math.isnan(value) for value in table.column("knee.speed")))
        self.assertEqual(table.provenance["knee.speed"]["missing_labels"], ("knee",))

    def test_trc_loader_reads_header_units_and_marker_names(self) -> None:
        content = "\n".join(
            (
                "PathFileType\t4\t(X/Y/Z)\tfixture.trc",
                "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
                "60\t60\t2\t1\tm\t60\t1\t2",
                "Frame#\tTime\tHip\t",
                "\t\tX1\tY1\tZ1",
                "1\t0.0\t1.0\t2.0\t3.0",
                "2\t0.0166667\t4.0\t5.0\t6.0",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.trc"
            path.write_text(content, encoding="utf-8")

            trajectory = Trajectory.from_trc(path, coordinate_system="world")

            self.assertEqual(trajectory.coordinate_unit, "m")
            self.assertEqual(trajectory.coordinate_system, "world")
            self.assertEqual(trajectory.frames, (1, 2))
            self.assertEqual(trajectory.points["Hip"][1], (4.0, 5.0, 6.0))
            self.assertEqual(trajectory.source_path, str(path))


if __name__ == "__main__":
    unittest.main()
