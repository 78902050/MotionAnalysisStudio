"""Qt-independent elapsed-time playback clock."""

from __future__ import annotations

from bisect import bisect_right
import math
from collections.abc import Sequence


class PlaybackClock:
    def __init__(self) -> None:
        self._running = False
        self._started_at = 0.0
        self._source_at_start = 0.0
        self._paused_time = 0.0
        self._speed = 1.0

    @property
    def running(self) -> bool:
        return self._running

    def start(self, now: float, source_time: float, speed: float = 1.0) -> None:
        values = (now, source_time, speed)
        if any(not math.isfinite(float(value)) for value in values) or speed <= 0:
            raise ValueError("playback clock values must be finite and speed must be positive")
        self._started_at = float(now)
        self._source_at_start = float(source_time)
        self._paused_time = float(source_time)
        self._speed = float(speed)
        self._running = True

    def pause(self, now: float) -> None:
        self._paused_time = self.time_at(now)
        self._running = False

    def time_at(self, now: float) -> float:
        if not self._running:
            return self._paused_time
        return self._source_at_start + (float(now) - self._started_at) * self._speed

    def frame_index(self, times: Sequence[float], now: float) -> int:
        if not times:
            raise ValueError("playback timeline must not be empty")
        index = bisect_right(times, self.time_at(now)) - 1
        return min(len(times) - 1, max(0, index))
