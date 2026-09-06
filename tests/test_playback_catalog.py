import tempfile
import unittest
from pathlib import Path

from app.playback.catalog import TrajectoryCatalog


class PlaybackCatalogTests(unittest.TestCase):
    def test_catalog_groups_pose2sim_variants_without_quality_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose3d = root / "pose-3d"
            pose3d.mkdir()
            for name in (
                "test1_P0_1-739_filt_butterworth_LSTM.c3d",
                "test1_P0_1-739.trc",
                "test1_P0_1-739_filt_butterworth.trc",
            ):
                (pose3d / name).touch()

            sources = TrajectoryCatalog.scan(root)

            self.assertEqual(
                [(item.person_id, item.variant, item.format) for item in sources],
                [
                    ("P0", "raw", "trc"),
                    ("P0", "butterworth", "trc"),
                    ("P0", "butterworth_lstm", "c3d"),
                ],
            )
            self.assertTrue(all(item.trial_id == "test1" for item in sources))

    def test_catalog_scans_only_direct_pose3d_files_and_parses_multiple_people(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose3d = root / "pose-3d"
            (pose3d / "nested").mkdir(parents=True)
            (pose3d / "trial_P2_10-20.trc").touch()
            (pose3d / "trial_P10_10-20.c3d").touch()
            (pose3d / "nested" / "ignored_P1_1-2.trc").touch()
            (root / "outside_P3_1-2.trc").touch()

            sources = TrajectoryCatalog.scan(root)

            self.assertEqual([item.person_id for item in sources], ["P2", "P10"])
            self.assertEqual([item.path.parent for item in sources], [pose3d.resolve()] * 2)

    def test_unknown_suffix_is_preserved_as_display_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose3d = root / "pose-3d"
            pose3d.mkdir()
            (pose3d / "jump_P1_1-60_custom-pass.trc").touch()

            source = TrajectoryCatalog.scan(root)[0]

            self.assertEqual(source.variant, "custom-pass")
            self.assertEqual(source.display_name, "jump · P1 · custom-pass · TRC")


if __name__ == "__main__":
    unittest.main()
