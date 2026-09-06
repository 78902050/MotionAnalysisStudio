import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.domain.addresses import FrameAddress
from app.gui.main_window import MainWindow
from app.media.frame_provider import MultiViewFrameProvider
from app.media.video_sources import CameraVideoSource
from app.project.manager import ProjectManager


class _PathCapture:
    def __init__(self, path: str) -> None:
        self.value = 17 if "first" in path else 83

    def isOpened(self) -> bool:
        return True

    def set(self, _prop: int, _value: float) -> bool:
        return True

    def read(self):
        return True, np.full((2, 2, 3), self.value, dtype=np.uint8)

    def release(self) -> None:
        pass


class _RecordingProvider(QObject):
    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def set_project(self, _project_id: str, _sources: object) -> None:
        self.events.append("set_project")

    def request(self, _address: FrameAddress, priority: int = 0) -> None:
        del priority
        self.events.append("request")

    def prefetch(self, _addresses: object) -> None:
        pass

    def clear(self) -> None:
        pass

    def close(self) -> bool:
        return True


class FrameProviderSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _wait_for(self, predicate, timeout: float = 1.5) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_source_object_drives_decode_and_is_exposed(self) -> None:
        provider = MultiViewFrameProvider(cache_capacity=2)
        received: list[object] = []
        provider.frame_ready.connect(lambda _camera, _frame, image: received.append(image))
        first = CameraVideoSource("cam01", Path("first.mp4"), "original")
        second = CameraVideoSource("cam01", Path("second.mp4"), "pose2sim_overlay")
        with patch("app.media.frame_provider.cv2.VideoCapture", _PathCapture):
            provider.set_project("project", {"cam01": first})
            provider.request(FrameAddress("cam01", "raw", 0))
            self.assertTrue(self._wait_for(lambda: len(received) == 1))
            provider.set_project("project", {"cam01": second})
            provider.request(FrameAddress("cam01", "raw", 0))
            self.assertTrue(self._wait_for(lambda: len(received) == 2))

        self.assertEqual(provider.source_for("cam01"), second)
        self.assertEqual(int(received[0][0, 0, 0]), 17)
        self.assertEqual(int(received[1][0, 0, 0]), 83)
        self.assertTrue(provider.close())

    def test_main_window_configures_provider_before_first_pose_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectManager.create(Path(directory) / "project", "首帧顺序")
            pose_dir = project.root / "pose" / "cam01_json"
            pose_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                Path("tests/fixtures/real_data/pose/cam01_json/cam01_000000.json"),
                pose_dir / "cam01_000000.json",
            )
            video = project.root / "cam01_pose.mp4"
            video.touch()
            project.manifest["cameras"] = [
                {"camera_id": "cam01", "pose_video_path": str(video)}
            ]
            project.save_manifest()
            provider = _RecordingProvider()
            window = MainWindow(frame_provider=provider)

            self.assertTrue(window.open_project(project))

            self.assertIn("request", provider.events)
            self.assertLess(provider.events.index("set_project"), provider.events.index("request"))
            window.close()


if __name__ == "__main__":
    unittest.main()
