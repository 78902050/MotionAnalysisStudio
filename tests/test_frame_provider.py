import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.domain.addresses import FrameAddress
from app.media.frame_provider import MultiViewFrameProvider


class _FakeCapture:
    thread_ids: list[int] = []
    instances: list["_FakeCapture"] = []
    read_delay = 0.002

    def __init__(self, path: str) -> None:
        self.path = path
        self.position = 0
        self.opened = True
        type(self).instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def set(self, _property: int, value: float) -> bool:
        self.position = int(value)
        return True

    def read(self):
        type(self).thread_ids.append(threading.get_ident())
        time.sleep(type(self).read_delay)
        return True, np.full((8, 8, 3), self.position % 255, dtype=np.uint8)

    def release(self) -> None:
        self.opened = False


class FrameProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        _FakeCapture.thread_ids.clear()
        _FakeCapture.instances.clear()
        _FakeCapture.read_delay = 0.002
        self.provider = MultiViewFrameProvider(cache_capacity=5)
        self.provider.set_project(
            "project-a",
            {f"cam0{index}": Path(f"cam0{index}.mp4") for index in range(1, 5)},
        )
        self.ready: list[tuple[str, int, object]] = []
        self.failed: list[tuple[str, int, str]] = []
        self.provider.frame_ready.connect(lambda camera, frame, image: self.ready.append((camera, frame, image)))
        self.provider.frame_failed.connect(lambda camera, frame, reason: self.failed.append((camera, frame, reason)))

    def tearDown(self) -> None:
        self.provider.close()

    def _wait_for(self, predicate, timeout_ms: int = 1500) -> bool:
        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < timeout_ms:
            self.application.processEvents()
            if predicate():
                return True
            QTest.qWait(5)
        return predicate()

    def test_video_capture_runs_on_worker_and_cache_is_bounded(self) -> None:
        gui_thread = threading.get_ident()
        with patch("app.media.frame_provider.cv2.VideoCapture", _FakeCapture):
            for frame in range(6):
                self.provider.request(FrameAddress("cam01", "raw", frame))
            self.assertTrue(self._wait_for(lambda: len(self.ready) >= 6))

        self.assertTrue(_FakeCapture.thread_ids)
        self.assertTrue(all(thread_id != gui_thread for thread_id in _FakeCapture.thread_ids))
        self.assertLessEqual(self.provider.cache_size, 5)

    def test_project_switch_discards_old_results(self) -> None:
        with patch("app.media.frame_provider.cv2.VideoCapture", _FakeCapture):
            self.provider.prefetch([FrameAddress("cam01", "raw", 1)])
            self.provider.set_project("project-b", {"cam01": Path("new.mp4")})
            self.provider.request(FrameAddress("cam01", "raw", 2))
            self.assertTrue(self._wait_for(lambda: any(frame == 2 for _, frame, _ in self.ready)))

        self.assertTrue(all(frame == 2 for _, frame, _ in self.ready))

    def test_four_camera_prefetch_keeps_qt_heartbeat_under_250ms(self) -> None:
        heartbeat_times: list[float] = []
        heartbeat = QTimer()
        heartbeat.setInterval(20)
        heartbeat.timeout.connect(lambda: heartbeat_times.append(time.monotonic()))
        heartbeat.start()
        addresses = [FrameAddress(f"cam0{index}", "raw", 0) for index in range(1, 5)]

        with patch("app.media.frame_provider.cv2.VideoCapture", _FakeCapture):
            self.provider.prefetch(addresses)
            QTest.qWait(2000)

        heartbeat.stop()
        self.assertGreater(len(heartbeat_times), 20)
        gaps = [right - left for left, right in zip(heartbeat_times, heartbeat_times[1:])]
        self.assertLess(max(gaps), 0.25)

    def test_four_cameras_decode_in_parallel(self) -> None:
        _FakeCapture.read_delay = 0.15
        addresses = [FrameAddress(f"cam0{index}", "raw", 0) for index in range(1, 5)]

        started = time.monotonic()
        with patch("app.media.frame_provider.cv2.VideoCapture", _FakeCapture):
            self.provider.prefetch(addresses)
            self.assertTrue(self._wait_for(lambda: len(self.ready) == 4, timeout_ms=1200))
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.45, "four camera reads were serialized")
        self.assertEqual(len(set(_FakeCapture.thread_ids)), 4)

    def test_project_switch_releases_previous_video_capture(self) -> None:
        with patch("app.media.frame_provider.cv2.VideoCapture", _FakeCapture):
            self.provider.request(FrameAddress("cam01", "raw", 0))
            self.assertTrue(self._wait_for(lambda: len(self.ready) == 1))
            old_capture = _FakeCapture.instances[0]

            self.provider.set_project("project-b", {"cam01": Path("new.mp4")})

            self.assertTrue(self._wait_for(lambda: not old_capture.opened, timeout_ms=1000))

    def test_close_reports_that_decoder_threads_stopped(self) -> None:
        self.assertTrue(self.provider.close())


if __name__ == "__main__":
    unittest.main()
