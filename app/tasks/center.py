"""Thread-based task center with project-generation result isolation."""

from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from .base import CancellationToken, TaskCancelled, TaskRequest, TaskResult


@dataclass
class _TaskState:
    request: TaskRequest
    token: CancellationToken
    done: Event
    result: TaskResult | None = None
    thread: Thread | None = None


class TaskCenter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[str, _TaskState] = {}

    def start(self, request: TaskRequest, work: Callable[[CancellationToken], object]) -> str:
        task_id = f"task-{uuid4().hex}"
        state = _TaskState(request, CancellationToken(), Event())

        def execute() -> None:
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
                state.done.set()

        thread = Thread(target=execute, name=f"motion-task-{task_id}", daemon=False)
        state.thread = thread
        with self._lock:
            self._tasks[task_id] = state
        thread.start()
        return task_id

    def cancel(self, task_id: str) -> None:
        state = self._get(task_id)
        state.token.cancel()

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

    @staticmethod
    def accepts_result(result: TaskResult, project_id: str, generation: int) -> bool:
        return result.project_id == project_id and result.generation == generation

    def _get(self, task_id: str) -> _TaskState:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"unknown task: {task_id}") from exc
