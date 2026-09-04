import json
import tempfile
import unittest
from pathlib import Path

from app.project.manager import ProjectManager
from app.synchronization.analyzer import SynchronizationAnalyzer
from app.synchronization.model import FrameMapping
from app.synchronization.overrides import SynchronizationOverride, SynchronizationOverrideStore


class SynchronizationTests(unittest.TestCase):
    def test_mapping_reads_camera_offsets_from_project_data_not_camera_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "同步测试")
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps(
                    {
                        "offsets": [
                            {"camera": "cam03", "frame_delta": -2, "source": "pose2sim"},
                            {"camera": "cam04", "frame_delta": 3, "source": "pose2sim"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            analyzer = SynchronizationAnalyzer()
            report = analyzer.analyze(project)
            cam03 = analyzer.mapping("cam03", 10)
            cam04 = analyzer.mapping("cam04", 10)

            self.assertEqual(report.mappings, ())
            self.assertEqual((cam03.source_frame, cam03.target_frame, cam03.method), (8, 10, "offset"))
            self.assertEqual((cam04.source_frame, cam04.target_frame), (13, 10))
            self.assertEqual(cam03.source, "pose2sim")

    def test_frame_table_timestamp_and_variable_offset_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "同步表")
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps(
                    {
                        "mappings": [
                            {"camera": "cam01", "source_frame": 100, "target_frame": 5, "method": "table", "source": "table.csv"},
                            {"camera": "cam02", "source_timestamp": 2.0, "target_timestamp": 2.5, "source_frame": 20, "target_frame": 8, "method": "timestamp", "source": "timestamps.csv"},
                        ],
                        "offsets": [
                            {"camera": "cam03", "start_frame": 0, "end_frame": 4, "frame_delta": 1, "source": "ranges.json"},
                            {"camera": "cam03", "start_frame": 5, "end_frame": 20, "frame_delta": 4, "source": "ranges.json"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            analyzer = SynchronizationAnalyzer()
            analyzer.analyze(project)

            self.assertIsInstance(analyzer.mapping("cam01", 5), FrameMapping)
            self.assertEqual(analyzer.mapping("cam01", 5).source_frame, 100)
            self.assertEqual(analyzer.mapping("cam02", 8).method, "timestamp")
            self.assertEqual(analyzer.mapping("cam03", 3).source_frame, 4)
            self.assertEqual(analyzer.mapping("cam03", 8).source_frame, 12)

    def test_unknown_camera_has_no_implicit_identity_or_special_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "未知相机")
            (root / "synchronization" / "mapping.json").write_text(
                json.dumps({"offsets": [{"camera": "cam01", "frame_delta": 2, "source": "mapping.json"}]}),
                encoding="utf-8",
            )
            analyzer = SynchronizationAnalyzer()
            analyzer.analyze(project)

            with self.assertRaises(KeyError):
                analyzer.mapping("cam99", 3)

    def test_manual_override_is_saved_and_loaded_without_touching_mapping_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = ProjectManager.create(root, "人工同步")
            mapping_path = root / "synchronization" / "mapping.json"
            original = '{"offsets":[{"camera":"cam01","frame_delta":1,"source":"source.json"}]}'
            mapping_path.write_text(original, encoding="utf-8")
            override = SynchronizationOverride("cam01", "manual", 5, mapping_path)

            store = SynchronizationOverrideStore(root)
            store.save(override)
            loaded = store.load()

            self.assertEqual(loaded, (override,))
            self.assertEqual(mapping_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
