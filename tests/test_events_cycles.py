import math
import tempfile
import unittest
from pathlib import Path

from app.analysis.cycles import CycleBuilder
from app.analysis.event_history import EventHistory
from app.analysis.events import EventDetector, EventRule, frame_for_time, time_for_frame
from app.analysis.model import MetricTable


def _metric_table(values: tuple[float, ...]) -> MetricTable:
    frames = tuple(range(len(values)))
    times = tuple(float(frame) for frame in frames)
    provenance = {
        "hip.speed": {
            "metric_id": "speed:hip",
            "input_labels": ("hip",),
            "input_source": "fixture.trc",
            "input_version": "fixture-v1",
        }
    }
    return MetricTable(
        frames,
        times,
        {"hip.speed": values},
        {"hip.speed": "m/s"},
        {"coordinate_system": "world", "coordinate_unit": "m", "sampling_rate_hz": 1.0},
        provenance,
    )


class EventCycleTests(unittest.TestCase):
    def test_threshold_events_are_deterministic_and_do_not_use_missing_values(self) -> None:
        table = _metric_table((0.0, 1.0, 2.0, math.nan, 3.0, 0.0, 4.0))
        rule = EventRule("speed-rise", "hip.speed", "crosses_above", 1.5, "速度上穿", "start")

        first = EventDetector().detect(table, rule)
        second = EventDetector().detect(table, rule)

        self.assertEqual([(event.frame, event.time) for event in first], [(2, 2.0), (6, 6.0)])
        self.assertEqual(first, second)
        self.assertEqual(first[0].segment_id, "segment-0")
        self.assertEqual(first[1].segment_id, "segment-4")

    def test_cycles_pair_events_without_crossing_data_segments(self) -> None:
        from app.analysis.events import Event

        events = (
            Event("start-1", "rule", "start", 1, 1.0, 1.0, "segment-0", "detected"),
            Event("end-1", "rule", "end", 3, 3.0, 2.0, "segment-0", "detected"),
            Event("start-2", "rule", "start", 4, 4.0, 1.0, "segment-4", "detected"),
            Event("end-2", "rule", "end", 6, 6.0, 2.0, "segment-6", "detected"),
        )

        cycles = CycleBuilder().build(events)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].start_frame, 1)
        self.assertEqual(cycles[0].end_frame, 3)
        self.assertEqual(cycles[0].duration, 2.0)

    def test_manual_event_history_overrides_detection_without_erasing_history(self) -> None:
        from app.analysis.events import Event

        detected = Event("event-1", "rule", "point", 2, 2.0, 1.0, "segment-0", "detected")
        manual = Event("event-1", "rule", "point", 3, 3.0, 1.0, "segment-0", "manual", "用户调整")
        with tempfile.TemporaryDirectory() as directory:
            history = EventHistory(Path(directory) / "events.jsonl")
            history.append(detected)
            history.append_manual(manual)

            effective = history.effective_events((detected,))

            self.assertEqual(effective, (manual,))
            self.assertEqual(len(history.records("event-1")), 2)
            self.assertEqual(history.records("event-1")[0].action, "detected")
            self.assertEqual(history.records("event-1")[1].action, "manual")

    def test_frame_time_lookup_is_exact_and_reversible(self) -> None:
        table = _metric_table((0.0, 1.0, 2.0))

        self.assertEqual(time_for_frame(table, 1), 1.0)
        self.assertEqual(frame_for_time(table, 2.0), 2)
        with self.assertRaises(KeyError):
            time_for_frame(table, 10)
        with self.assertRaises(ValueError):
            frame_for_time(table, 1.5)


if __name__ == "__main__":
    unittest.main()
