"""Background multi-camera frame decoding with project-isolated results."""

from __future__ import annotations

import heapq
import threading
from dataclasses import dataclass
from pathlib import Path
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
    video_path: Path


class _DecodeThread(QThread):
    """Owns all VideoCapture objects and performs every read in its run loop."""

    result_ready = Signal(str, int, object, str, int)
    result_failed = Signal(str, int, str, str, int)

    def __init__(self) -> None:
        super().__init__()
        self._condition = threading.Condition()
        self._queue: list[tuple[int, int, _DecodeRequest]] = []
        self._sequence = 0
        self._stop_requested = False
        self._generation = 0
        self._cancelled_groups: set[str] = set()

    def enqueue(
        self,
        address: FrameAddress,
        video_path: Path,
        project_id: str,
        generation: int,
        priority: int,
        group: str,
    ) -> None:
        with self._condition:
            request = _DecodeRequest(
                priority=priority,
                sequence=self._sequence,
                group=group,
                project_id=project_id,
                generation=generation,
                address=address,
                video_path=video_path,
            )
            self._sequence += 1
            self._cancelled_groups.discard(group)
            heapq.heappush(self._queue, (request.priority, request.sequence, request))
            self._condition.notify()

    def set_generation(self, generation: int) -> None:
        with self._condition:
            self._generation = generation
            self._condition.notify_all()

    def cancel_group(self, request_group: str) -> None:
        with self._condition:
            self._cancelled_groups.add(request_group)
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
            if request.generation != self._generation or request.group in self._cancelled_groups:
                return _DecodeRequest(
                    priority=-1,
                    sequence=-1,
                    group="__cancelled__",
                    project_id="",
                    generation=-1,
                    address=request.address,
                    video_path=request.video_path,
                )
            return request

    def run(self) -> None:
        captures: dict[Path, cv2.VideoCapture] = {}
        try:
            while True:
                request = self._take_request()
                if request is None:
                    return
                if request.group == "__cancelled__":
                    continue

                address = request.address
                capture = captures.get(request.video_path)
                if capture is None:
                    capture = cv2.VideoCapture(str(request.video_path))
                    if not capture.isOpened():
                        self.result_failed.emit(
                            address.camera,
                            address.frame,
                            f"无法打开视频：{request.video_path}",
                            request.project_id,
                            request.generation,
                        )
                        capture.release()
                        continue
                    captures[request.video_path] = capture

                capture.set(cv2.CAP_PROP_POS_FRAMES, address.frame)
                success, image = capture.read()
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
            for capture in captures.values():
                capture.release()


class MultiViewFrameProvider(QObject):
    """Submit-only GUI facade for background raw-video frame decoding."""

    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)

    def __init__(self, cache_capacity: int = 5) -> None:
        super().__init__()
        self._cache: LruFrameCache[tuple[str, str, int], object] = LruFrameCache(cache_capacity)
        self._worker = _DecodeThread()
        self._worker.result_ready.connect(self._on_frame_ready)
        self._worker.result_failed.connect(self._on_frame_failed)
        self._project_id = ""
        self._videos: dict[str, Path] = {}
        self._generation = 0
        self._prefetch_group = ""
        self._group_sequence = 0
        self._closed = False
        self._worker.start()

    def set_project(self, project_id: str, videos: dict[str, Path]) -> None:
        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        self._generation += 1
        self._project_id = project_id
        self._videos = {camera: Path(path) for camera, path in videos.items()}
        self._cache.clear()
        if self._prefetch_group:
            self._worker.cancel_group(self._prefetch_group)
        self._prefetch_group = ""
        self._worker.set_generation(self._generation)

    def request(self, address: FrameAddress, priority: int = 0) -> None:
        self._validate_address(address)
        if priority <= 0 and self._prefetch_group:
            self._worker.cancel_group(self._prefetch_group)
            self._prefetch_group = ""
        self._submit(address, priority=priority, group="navigation")

    def prefetch(self, addresses: Iterable[FrameAddress]) -> None:
        self._group_sequence += 1
        group = f"prefetch-{self._group_sequence}"
        if self._prefetch_group:
            self._worker.cancel_group(self._prefetch_group)
        self._prefetch_group = group
        for address in addresses:
            self._validate_address(address)
            self._submit(address, priority=10, group=group)

    def cancel(self, request_group: str) -> None:
        self._worker.cancel_group(request_group)
        if request_group == self._prefetch_group:
            self._prefetch_group = ""

    def clear(self) -> None:
        self._generation += 1
        self._cache.clear()
        self._prefetch_group = ""
        self._worker.set_generation(self._generation)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.clear()
        self._worker.stop()
        self._worker.wait(3000)

    def _validate_address(self, address: FrameAddress) -> None:
        if address.timeline != "raw":
            raise ValueError("MultiViewFrameProvider reads raw video frames only")

    def _submit(self, address: FrameAddress, priority: int, group: str) -> None:
        if self._closed:
            return
        video_path = self._videos.get(address.camera)
        if video_path is None:
            self.frame_failed.emit(address.camera, address.frame, "未配置该相机的视频文件")
            return
        key = (self._project_id, address.camera, address.frame)
        image = self._cache.get(key)
        if image is not None:
            self.frame_ready.emit(address.camera, address.frame, image)
            return
        self._worker.enqueue(
            address=address,
            video_path=video_path,
            project_id=self._project_id,
            generation=self._generation,
            priority=priority,
            group=group,
        )

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
