"""Thread-based task center with project-generation result isolation."""

from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from .base import (
    CancellationToken,
    SupervisorTaskStatus,
    TaskCancelled,
    TaskRequest,
    TaskResult,
    TaskSnapshot,
)
from .handle import TaskHandle


@dataclass
class _TaskState:
    request: TaskRequest
    token: CancellationToken
    done: Event
    status: SupervisorTaskStatus = "queued"
    result: TaskResult | None = None
    thread: Thread | None = None


class TaskCenter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[str, _TaskState] = {}

    def start(self, request: TaskRequest, work: Callable[[CancellationToken], object]) -> str:
        return self.start_handle(request, work).task_id

    def start_handle(
        self, request: TaskRequest, work: Callable[[CancellationToken], object]
    ) -> TaskHandle:
        task_id = f"task-{uuid4().hex}"
        state = _TaskState(request, CancellationToken(), Event())

        def execute() -> None:
            with self._lock:
                if state.status == "queued":
                    state.status = "running"
            try:
                value = work(state.token)
                status = "cancelled" if state.token.is_cancelled else "succeeded"
                state.result = TaskResult(
                    task_id, request.project_id, request.generation, request.name, status, value=value
                )
            except TaskCancelled:
                state.result = TaskResult(
                    task_id, request.project_id, request.generation, request.name, "cancelled"
                )
            except Exception as exc:  # task failures must be returned to the caller
                state.result = TaskResult(
                    task_id,
                    request.project_id,
                    request.generation,
                    request.name,
                    "failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                with self._lock:
                    assert state.result is not None
                    state.status = {
                        "succeeded": "completed",
                        "failed": "failed",
                        "cancelled": "cancelled",
                    }[state.result.status]
                state.done.set()

        thread = Thread(target=execute, name=f"motion-task-{task_id}", daemon=False)
        state.thread = thread
        with self._lock:
            self._tasks[task_id] = state
        thread.start()
        return TaskHandle(
            task_id,
            request.project_id,
            request.generation,
            request.name,
            lambda: self.cancel(task_id),
            lambda timeout=None: self.wait(task_id, timeout),
        )

    def cancel(self, task_id: str) -> None:
        with self._lock:
            try:
                state = self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"unknown task: {task_id}") from exc
            state.token.cancel()
            if state.status in {"queued", "running"}:
                state.status = "cancelling"

    def wait(self, task_id: str, timeout: float | None = None) -> TaskResult:
        state = self._get(task_id)
        if not state.done.wait(timeout):
            raise TimeoutError(f"task did not finish: {task_id}")
        assert state.result is not None
        return state.result

    def wait_for_shutdown(self, timeout_ms: int) -> bool:
        deadline = monotonic() + max(timeout_ms, 0) / 1000
        with self._lock:
            states = list(self._tasks.values())
        for state in states:
            remaining = max(0.0, deadline - monotonic())
            if state.thread is not None:
                state.thread.join(remaining)
        return all(state.thread is None or not state.thread.is_alive() for state in states)

    def snapshot(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            try:
                state = self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"unknown task: {task_id}") from exc
            result = state.result
            return TaskSnapshot(
                task_id,
                state.request.project_id,
                state.request.generation,
                state.request.name,
                state.status,
                result.error if result is not None else None,
            )

    @staticmethod
    def accepts_result(result: TaskResult, project_id: str, generation: int) -> bool:
        return result.project_id == project_id and result.generation == generation

    def _get(self, task_id: str) -> _TaskState:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"unknown task: {task_id}") from exc
