"""Parallel per-camera frame decoding with project-isolated results."""

from __future__ import annotations

import heapq
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Iterable

import cv2
from PySide6.QtCore import QObject, QThread, Signal

from app.domain.addresses import FrameAddress

from .lru_cache import LruFrameCache


@dataclass(frozen=True)
class _DecodeRequest:
    priority: int
    sequence: int
    group: str
    project_id: str
    generation: int
    address: FrameAddress


class _CameraDecodeThread(QThread):
    """Own one camera's VideoCapture and serialize only that camera's requests."""

    result_ready = Signal(str, int, object, str, int)
    result_failed = Signal(str, int, str, str, int)

    def __init__(self, camera: str, video_path: Path) -> None:
        super().__init__()
        self.camera = camera
        self.video_path = Path(video_path)
        self._condition = threading.Condition()
        self._queue: list[tuple[int, int, _DecodeRequest]] = []
        self._sequence = 0
        self._stop_requested = False
        self._cancelled_groups: set[str] = set()

    def enqueue(
        self,
        address: FrameAddress,
        project_id: str,
        generation: int,
        priority: int,
        group: str,
    ) -> None:
        with self._condition:
            request = _DecodeRequest(
                priority,
                self._sequence,
                group,
                project_id,
                generation,
                address,
            )
            self._sequence += 1
            self._cancelled_groups.discard(group)
            heapq.heappush(self._queue, (request.priority, request.sequence, request))
            self._condition.notify()

    def cancel_group(self, request_group: str) -> None:
        with self._condition:
            self._cancelled_groups.add(request_group)
            self._condition.notify_all()

    def cancel_all(self) -> None:
        with self._condition:
            self._queue.clear()
            self._cancelled_groups.clear()
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._queue.clear()
            self._condition.notify_all()

    def _take_request(self) -> _DecodeRequest | None:
        with self._condition:
            while not self._queue and not self._stop_requested:
                self._condition.wait(timeout=0.1)
            if self._stop_requested:
                return None
            _, _, request = heapq.heappop(self._queue)
            return request

    def _is_cancelled(self, group: str) -> bool:
        with self._condition:
            return self._stop_requested or group in self._cancelled_groups

    def run(self) -> None:
        capture: cv2.VideoCapture | None = None
        last_frame: int | None = None
        try:
            while True:
                request = self._take_request()
                if request is None:
                    return
                if self._is_cancelled(request.group):
                    continue
                address = request.address
                if capture is None:
                    capture = cv2.VideoCapture(str(self.video_path))
                    if not capture.isOpened():
                        self.result_failed.emit(
                            address.camera,
                            address.frame,
                            f"无法打开视频：{self.video_path}",
                            request.project_id,
                            request.generation,
                        )
                        capture.release()
                        capture = None
                        continue
                if last_frame is None or address.frame != last_frame + 1:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, address.frame)
                success, image = capture.read()
                last_frame = address.frame if success else None
                if self._is_cancelled(request.group):
                    continue
                if not success or image is None:
                    self.result_failed.emit(
                        address.camera,
                        address.frame,
                        "读取视频帧失败",
                        request.project_id,
                        request.generation,
                    )
                    continue
                self.result_ready.emit(
                    address.camera,
                    address.frame,
                    image,
                    request.project_id,
                    request.generation,
                )
        finally:
            if capture is not None:
                capture.release()


class MultiViewFrameProvider(QObject):
    """Submit-only GUI facade for background raw-video frame decoding."""

    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)

    def __init__(self, cache_capacity: int = 20) -> None:
        super().__init__()
        self._cache: LruFrameCache[tuple[str, str, int], object] = LruFrameCache(cache_capacity)
        self._workers: dict[str, _CameraDecodeThread] = {}
        self._retired_workers: list[_CameraDecodeThread] = []
        self._project_id = ""
        self._videos: dict[str, Path] = {}
        self._generation = 0
        self._prefetch_group = ""
        self._group_sequence = 0
        self._closed = False

    def set_project(self, project_id: str, videos: dict[str, Path]) -> None:
        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        self._generation += 1
        self._stop_workers(3000)
        self._project_id = project_id
        self._videos = {camera: Path(path) for camera, path in videos.items()}
        self._cache.clear()
        self._prefetch_group = ""
        self._closed = False
        for camera, video_path in self._videos.items():
            worker = _CameraDecodeThread(camera, video_path)
            worker.result_ready.connect(self._on_frame_ready)
            worker.result_failed.connect(self._on_frame_failed)
            self._workers[camera] = worker
            worker.start()

    def request(self, address: FrameAddress, priority: int = 0) -> None:
        self._validate_address(address)
        if priority <= 0 and self._prefetch_group:
            self.cancel(self._prefetch_group)
        self._submit(address, priority=priority, group="navigation")

    def prefetch(self, addresses: Iterable[FrameAddress]) -> None:
        self._group_sequence += 1
        group = f"prefetch-{self._group_sequence}"
        if self._prefetch_group:
            self.cancel(self._prefetch_group)
        self._prefetch_group = group
        for address in addresses:
            self._validate_address(address)
            self._submit(address, priority=10, group=group)

    def cancel(self, request_group: str) -> None:
        for worker in self._workers.values():
            worker.cancel_group(request_group)
        if request_group == self._prefetch_group:
            self._prefetch_group = ""

    def clear(self) -> None:
        self._generation += 1
        self._cache.clear()
        self._prefetch_group = ""
        for worker in self._workers.values():
            worker.cancel_all()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def close(self) -> bool:
        if self._closed and not self._workers and not self._retired_workers:
            return True
        self._closed = True
        self.clear()
        return self._stop_workers(3000)

    def _stop_workers(self, timeout_ms: int) -> bool:
        workers = [*self._retired_workers, *self._workers.values()]
        self._workers.clear()
        self._retired_workers = []
        for worker in workers:
            worker.stop()
        deadline = monotonic() + max(timeout_ms, 0) / 1000
        for worker in workers:
            remaining_ms = max(0, int((deadline - monotonic()) * 1000))
            if not worker.wait(remaining_ms):
                self._retired_workers.append(worker)
        return not self._retired_workers

    @staticmethod
    def _validate_address(address: FrameAddress) -> None:
        if address.timeline != "raw":
            raise ValueError("MultiViewFrameProvider reads raw video frames only")

    def _submit(self, address: FrameAddress, priority: int, group: str) -> None:
        if self._closed:
            return
        worker = self._workers.get(address.camera)
        if worker is None:
            self.frame_failed.emit(address.camera, address.frame, "未配置该相机的视频文件")
            return
        key = (self._project_id, address.camera, address.frame)
        image = self._cache.get(key)
        if image is not None:
            self.frame_ready.emit(address.camera, address.frame, image)
            return
        worker.enqueue(address, self._project_id, self._generation, priority, group)

    def _on_frame_ready(
        self,
        camera: str,
        frame: int,
        image: object,
        project_id: str,
        generation: int,
    ) -> None:
        if project_id != self._project_id or generation != self._generation:
            return
        self._cache.put((project_id, camera, frame), image)
        self.frame_ready.emit(camera, frame, image)

    def _on_frame_failed(
        self,
        camera: str,
        frame: int,
        reason: str,
        project_id: str,
        generation: int,
    ) -> None:
        if project_id != self._project_id or generation != self._generation:
            return
        self.frame_failed.emit(camera, frame, reason)
