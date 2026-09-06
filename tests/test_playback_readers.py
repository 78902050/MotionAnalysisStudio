import math
import tempfile
import unittest
from pathlib import Path

import c3d
import numpy as np

from app.analysis.model import Trajectory
from app.playback.model import TrajectorySource
from app.playback.readers import load_playback_trajectory


def _write_trc(path: Path, *, declared_frames: int, rows: list[tuple[int, float, float]]) -> None:
    lines = [
        f"PathFileType\t4\t(X/Y/Z)\t{path.name}",
        "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames",
        f"60\t60\t{declared_frames}\t1\tmm\t60\t1\t{declared_frames}",
        "Frame#\tTime\tHip\t\t",
        "\t\tX1\tY1\tZ1",
        *[f"{frame}\t{time}\t{x}\t2\t3" for frame, time, x in rows],
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_c3d(path: Path) -> None:
    writer = c3d.Writer(point_rate=60.0, point_units="mm  ")
    writer.set_point_labels(["Hip   "])
    valid = np.array([[1.0, 2.0, 3.0, 0.5, 1.0]])
    invalid = np.array([[4.0, 5.0, 6.0, -1.0, 0.0]])
    analog = np.empty((0, 0))
    writer.add_frames([(valid, analog), (invalid, analog)])
    with path.open("wb") as handle:
        writer.write(handle)


class PlaybackReaderTests(unittest.TestCase):
    def test_trc_loads_actual_rows_and_reports_header_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trial_P0_1-3.trc"
            _write_trc(path, declared_frames=3, rows=[(1, 0.0, 1.0), (2, 1 / 60, 2.0)])
            source = TrajectorySource(path, "trc", "trial", "P0", "raw")

            trajectory = load_playback_trajectory(source)

            self.assertEqual(trajectory.frames, (1, 2))
            self.assertEqual(trajectory.coordinate_unit, "mm")
            self.assertEqual(trajectory.diagnostics[0].code, "frame_count_mismatch")
            with self.assertRaisesRegex(ValueError, "declares 3 frames"):
                Trajectory.from_trc(path, "world")

    def test_trc_rejects_non_increasing_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trial_P0_1-2.trc"
            _write_trc(path, declared_frames=2, rows=[(1, 0.0, 1.0), (2, 0.0, 2.0)])
            source = TrajectorySource(path, "trc", "trial", "P0", "raw")
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                load_playback_trajectory(source)

    def test_c3d_trims_labels_and_converts_invalid_residual_to_nan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trial_P0_1-2.c3d"
            _write_c3d(path)
            source = TrajectorySource(path, "c3d", "trial", "P0", "raw")

            trajectory = load_playback_trajectory(source)

            self.assertEqual(tuple(trajectory.points), ("Hip",))
            self.assertEqual(trajectory.coordinate_unit, "mm")
            self.assertEqual(trajectory.points["Hip"][0], (1.0, 2.0, 3.0))
            self.assertTrue(all(math.isnan(value) for value in trajectory.points["Hip"][1]))
            self.assertEqual(len(trajectory.frames), 2)


if __name__ == "__main__":
    unittest.main()
