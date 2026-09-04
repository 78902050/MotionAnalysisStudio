import math
import tempfile
import unittest
from pathlib import Path

from app.analysis.comparison import ComparisonMember, ComparisonRequest, ComparisonService
from app.analysis.events import Event
from app.analysis.model import MetricTable


def _table(frames: tuple[int, ...], times: tuple[float, ...], values: tuple[float, ...], version: str) -> MetricTable:
    return MetricTable(
        frames,
        times,
        {"hip.speed": values},
        {"hip.speed": "m/s"},
        {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
        {"hip.speed": {"metric_id": "speed:hip", "input_labels": ("hip",), "input_version": version}},
    )


class ComparisonReportingTests(unittest.TestCase):
    def _service(self) -> ComparisonService:
        first = ComparisonMember("project-a", "person-1", "trial-1", _table((0, 1, 2), (0.0, 1.0, 2.0), (1.0, math.nan, 3.0), "a-v1"))
        second = ComparisonMember("project-b", "person-1", "trial-1", _table((0, 2, 3), (0.0, 2.0, 3.0), (2.0, 4.0, 6.0), "b-v4"))
        return ComparisonService((first, second))

    def test_time_comparison_selects_explicit_members_and_keeps_missing_values(self) -> None:
        request = ComparisonRequest(("project-a", "project-b"), ("person-1",), ("trial-1",), "time")

        report = self._service().build(request)

        self.assertEqual(report.report_version, "comparison-v1")
        self.assertEqual(report.member_ids, ("project-a/person-1/trial-1", "project-b/person-1/trial-1"))
        self.assertEqual(report.metadata["alignment_source"], "exact metric times; no interpolation")
        missing_value = next(
            row for row in report.rows if row.member_id == "project-a/person-1/trial-1" and row.time == 1.0
        )
        missing_sample = next(
            row for row in report.rows if row.member_id == "project-b/person-1/trial-1" and row.time == 1.0
        )
        self.assertIsNone(missing_value.value)
        self.assertEqual(missing_value.missing_reason, "missing_value")
        self.assertIsNone(missing_sample.value)
        self.assertEqual(missing_sample.missing_reason, "sample_missing")

    def test_event_alignment_uses_event_occurrence_and_input_versions(self) -> None:
        first = ComparisonMember(
            "project-a",
            "person-1",
            "trial-1",
            _table((0, 1, 2), (0.0, 1.0, 2.0), (1.0, 2.0, 3.0), "a-v1"),
            (Event("a-contact", "contact", "point", 1, 1.0, 2.0, "segment-0"),),
        )
        second = ComparisonMember(
            "project-b",
            "person-1",
            "trial-1",
            _table((0, 1, 2), (0.0, 1.0, 2.0), (4.0, 5.0, 6.0), "b-v4"),
            (Event("b-contact", "contact", "point", 2, 2.0, 6.0, "segment-0"),),
        )

        report = ComparisonService((first, second)).build(
            ComparisonRequest(("project-a", "project-b"), ("person-1",), ("trial-1",), "event")
        )

        self.assertEqual(report.metadata["alignment_source"], "event rule and occurrence; exact event frame")
        self.assertEqual({row.alignment_key for row in report.rows}, {"contact:0"})
        self.assertEqual(
            {row.member_id: row.frame for row in report.rows},
            {"project-a/person-1/trial-1": 1, "project-b/person-1/trial-1": 2},
        )
        self.assertEqual(report.metadata["input_versions"], {"project-a/person-1/trial-1": "a-v1", "project-b/person-1/trial-1": "b-v4"})

    def test_exports_are_stable_and_can_be_read_back(self) -> None:
        report = self._service().build(
            ComparisonRequest(("project-a", "project-b"), ("person-1",), ("trial-1",), "frame")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contents: dict[str, bytes] = {}
            for format_name in ("json", "csv", "html"):
                path = root / f"comparison.{format_name}"
                self._service().export(report, path, format_name)
                contents[format_name] = path.read_bytes()
                self.assertTrue(contents[format_name])
                self._service().export(report, path, format_name)
                self.assertEqual(contents[format_name], path.read_bytes())
            self.assertIn(b"comparison-v1", contents["json"])
            self.assertIn(b"missing_value", contents["csv"])
            self.assertIn(b"<table", contents["html"])

    def test_invalid_selection_and_alignment_are_rejected(self) -> None:
        service = self._service()
        with self.assertRaises(ValueError):
            service.build(ComparisonRequest(("project-a",), ("person-unknown",), ("trial-1",), "frame"))
        with self.assertRaises(ValueError):
            ComparisonRequest(("project-a",), ("person-1",), ("trial-1",), "sample")


if __name__ == "__main__":
    unittest.main()
