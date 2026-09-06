import unittest

from app.playback.clock import PlaybackClock


class PlaybackClockTests(unittest.TestCase):
    def test_clock_uses_elapsed_time_instead_of_tick_count(self) -> None:
        clock = PlaybackClock()
        clock.start(now=10.0, source_time=1.0, speed=2.0)

        self.assertEqual(clock.time_at(10.5), 2.0)
        self.assertEqual(clock.frame_index((1.0, 1.5, 2.0), 10.5), 2)

    def test_pause_freezes_source_time_and_restart_continues(self) -> None:
        clock = PlaybackClock()
        clock.start(now=1.0, source_time=0.5, speed=1.0)
        clock.pause(now=2.0)
        self.assertEqual(clock.time_at(9.0), 1.5)
        clock.start(now=10.0, source_time=clock.time_at(10.0), speed=0.5)
        self.assertEqual(clock.time_at(12.0), 2.5)

    def test_frame_index_clamps_before_and_after_timeline(self) -> None:
        clock = PlaybackClock()
        self.assertEqual(clock.frame_index((1.0, 2.0, 3.0), now=0.0), 0)
        clock.start(now=0.0, source_time=10.0, speed=1.0)
        self.assertEqual(clock.frame_index((1.0, 2.0, 3.0), now=0.0), 2)


if __name__ == "__main__":
    unittest.main()
