"""Allow-listed, logged Pose2Sim stage execution."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable
from uuid import uuid4

from app.tasks.base import TaskRequest

from .stage_process import terminate_process


@dataclass(frozen=True)
class RunResult:
    task_id: str
    project_id: str
    generation: int
    stages: tuple[str, ...]
    succeeded: bool
    cancelled: bool
    log_path: Path
    error: str | None = None


@dataclass
class _RunState:
    request: TaskRequest
    stages: tuple[str, ...]
    cancel_event: Event
    done: Event
    result: RunResult | None = None
    process: subprocess.Popen[object] | None = None
    thread: Thread | None = None


@dataclass(frozen=True)
class PipelineRunHandle:
    task_id: str
    project_id: str
    generation: int
    _cancel: Callable[[], None]
    _wait: Callable[[float | None], RunResult]

    def cancel(self) -> None:
        self._cancel()

    def wait(self, timeout: float | None = None) -> RunResult:
        return self._wait(timeout)


class PipelineRunner:
    def __init__(
        self,
        commands: dict[str, list[str] | tuple[str, ...]],
        allowed_stages: tuple[str, ...],
        log_dir: Path,
    ) -> None:
        self.commands = {stage: tuple(command) for stage, command in commands.items()}
        self.allowed_stages = frozenset(allowed_stages)
        self.log_dir = Path(log_dir)
        self._lock = Lock()
        self._states: dict[str, _RunState] = {}

    def run(self, request: TaskRequest, stages: tuple[str, ...] | list[str]) -> RunResult:
        return self.start(request, stages).wait()

    def start(
        self, request: TaskRequest, stages: tuple[str, ...] | list[str]
    ) -> PipelineRunHandle:
        stages = tuple(stages)
        self._validate_stages(stages)
        task_id = f"task-{uuid4().hex}"
        state = _RunState(request, stages, Event(), Event())
        thread = Thread(
            target=self._execute,
            args=(task_id, state),
            name=f"pose2sim-{task_id}",
            daemon=False,
        )
        state.thread = thread
        with self._lock:
            self._states[task_id] = state
        thread.start()
        return PipelineRunHandle(
            task_id,
            request.project_id,
            request.generation,
            lambda: self.cancel(task_id),
            lambda timeout=None: self._wait(task_id, timeout),
        )

    def _validate_stages(self, stages: tuple[str, ...]) -> None:
        if not stages:
            raise ValueError("at least one stage is required")
        disallowed = [stage for stage in stages if stage not in self.allowed_stages]
        if disallowed:
            raise ValueError(f"stages are not allowed: {', '.join(disallowed)}")
        missing_commands = [stage for stage in stages if stage not in self.commands]
        if missing_commands:
            raise ValueError(f"no command configured for: {', '.join(missing_commands)}")

    def _execute(self, task_id: str, state: _RunState) -> None:
        request = state.request
        stages = state.stages
        cancel_event = state.cancel_event
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{task_id}.log"
        error: str | None = None
        cancelled = False
        succeeded = True

        try:
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                log.write(f"project_id={request.project_id}\n")
                log.write(f"generation={request.generation}\n")
                for stage in stages:
                    if cancel_event.is_set():
                        cancelled = True
                        succeeded = False
                        break
                    command = self.commands[stage]
                    log.write(f"[{stage}] command={subprocess.list2cmdline(command)}\n")
                    log.flush()
                    process = subprocess.Popen(
                        command,
                        stdout=log,
                        stderr=log,
                        cwd=request.payload.get("working_directory")
                        if isinstance(request.payload.get("working_directory"), str)
                        else None,
                    )
                    with self._lock:
                        state.process = process
                    try:
                        while process.poll() is None:
                            if cancel_event.wait(0.05):
                                terminate_process(process)
                                cancelled = True
                                succeeded = False
                                break
                        return_code = process.wait()
                    finally:
                        with self._lock:
                            state.process = None
                    if cancelled:
                        break
                    if return_code != 0:
                        succeeded = False
                        error = f"stage {stage} exited with code {return_code}"
                        break
                log.flush()
        except Exception as exc:
            succeeded = False
            error = f"{type(exc).__name__}: {exc}"
        finally:
            state.result = RunResult(
                task_id,
                request.project_id,
                request.generation,
                stages,
                succeeded,
                cancelled,
                log_path,
                error,
            )
            state.done.set()

    def _wait(self, task_id: str, timeout: float | None) -> RunResult:
        with self._lock:
            try:
                state = self._states[task_id]
            except KeyError as exc:
                raise KeyError(f"unknown pipeline task: {task_id}") from exc
        if not state.done.wait(timeout):
            raise TimeoutError(f"pipeline task did not finish: {task_id}")
        assert state.result is not None
        return state.result

    def cancel(self, task_id: str) -> None:
        with self._lock:
            state = self._states.get(task_id)
            if state is None:
                return
            state.cancel_event.set()
            process = state.process
        if process is None:
            return
        terminate_process(process)
