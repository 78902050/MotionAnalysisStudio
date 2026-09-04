"""Allow-listed, logged Pose2Sim stage execution."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from time import monotonic
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
        self._active: dict[str, tuple[Event, subprocess.Popen[object]]] = {}

    def run(self, request: TaskRequest, stages: tuple[str, ...] | list[str]) -> RunResult:
        stages = tuple(stages)
        if not stages:
            raise ValueError("at least one stage is required")
        disallowed = [stage for stage in stages if stage not in self.allowed_stages]
        if disallowed:
            raise ValueError(f"stages are not allowed: {', '.join(disallowed)}")
        missing_commands = [stage for stage in stages if stage not in self.commands]
        if missing_commands:
            raise ValueError(f"no command configured for: {', '.join(missing_commands)}")

        task_id = f"task-{uuid4().hex}"
        cancel_event = Event()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{task_id}.log"
        error: str | None = None
        cancelled = False
        succeeded = True

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
                    cwd=request.payload.get("working_directory") if isinstance(request.payload.get("working_directory"), str) else None,
                )
                with self._lock:
                    self._active[task_id] = (cancel_event, process)
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
                        self._active.pop(task_id, None)
                if cancelled:
                    break
                if return_code != 0:
                    succeeded = False
                    error = f"stage {stage} exited with code {return_code}"
                    break
            log.flush()

        return RunResult(
            task_id,
            request.project_id,
            request.generation,
            stages,
            succeeded,
            cancelled,
            log_path,
            error,
        )

    def cancel(self, task_id: str) -> None:
        with self._lock:
            active = self._active.get(task_id)
        if active is None:
            return
        cancel_event, process = active
        cancel_event.set()
        terminate_process(process)
