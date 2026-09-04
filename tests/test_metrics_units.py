import math
import unittest

from app.analysis.metrics import MetricEngine
from app.analysis.model import MetricConfig, MetricDefinition, Trajectory


class MetricUnitTests(unittest.TestCase):
    def test_angle_definition_in_radians_returns_radians(self) -> None:
        trajectory = Trajectory(
            frames=(0, 1),
            times=(0.0, 1.0),
            points={
                "hip": ((0.0, 0.0, 0.0),) * 2,
                "shoulder": ((1.0, 0.0, 0.0),) * 2,
                "elbow": ((1.0, 1.0, 0.0),) * 2,
            },
            coordinate_unit="m",
            coordinate_system="world",
        )

        table = MetricEngine().calculate(
            trajectory,
            (MetricDefinition("angle:hip:shoulder:elbow", "rad", ("hip", "shoulder", "elbow")),),
            MetricConfig(1.0, "m", None),
        )

        self.assertAlmostEqual(table.column("angle.hip.shoulder.elbow")[0], math.pi / 2)


if __name__ == "__main__":
    unittest.main()
