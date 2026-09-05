"""Non-blocking subprocess launcher with UTF-8 project logs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event, Lock, Thread
from typing import BinaryIO, Iterable

from app.adapters.pose2sim.stage_process import terminate_process


class ExternalToolLaunchError(RuntimeError):
    pass


class ExternalProcessHandle:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        thread: Thread,
        done: Event,
        log_path: Path,
    ) -> None:
        self.process = process
        self.thread = thread
        self.done = done
        self.log_path = Path(log_path)
        self._cancel_lock = Lock()

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        if not self.done.wait(timeout):
            raise TimeoutError("external process did not finish")
        self.thread.join(timeout=0)
        return int(self.process.returncode)

    def cancel(self) -> None:
        with self._cancel_lock:
            terminate_process(self.process)
        self.done.wait(3)

    def close(self) -> bool:
        self.cancel()
        return not self.thread.is_alive()


class ExternalToolLauncher:
    def start(
        self,
        command: Iterable[str],
        cwd: Path,
        log_path: Path,
    ) -> ExternalProcessHandle:
        command_tuple = tuple(str(part) for part in command)
        if not command_tuple or not command_tuple[0].strip():
            raise ExternalToolLaunchError("外部工具命令为空")
        cwd = Path(cwd)
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_log_header(log_path, command_tuple, cwd)
        try:
            process = subprocess.Popen(
                command_tuple,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            with log_path.open("a", encoding="utf-8", newline="\n") as log:
                log.write(f"launch_error={type(exc).__name__}: {exc}\n")
            raise ExternalToolLaunchError(f"无法启动外部工具：{exc}") from exc

        done = Event()

        def collect_output() -> None:
            try:
                with log_path.open("a", encoding="utf-8", newline="\n") as log:
                    self._copy_output(process.stdout, log)
                    return_code = process.wait()
                    log.write(f"exit_code={return_code}\n")
                    log.flush()
            finally:
                done.set()

        thread = Thread(
            target=collect_output,
            name=f"external-tool-{process.pid}",
            daemon=False,
        )
        thread.start()
        return ExternalProcessHandle(process, thread, done, log_path)

    @staticmethod
    def _copy_output(source: BinaryIO | None, destination) -> None:
        if source is None:
            return
        for line in iter(source.readline, b""):
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError:
                text = line.decode("gb18030", errors="replace")
            destination.write(text)
            destination.flush()
        source.close()

    @staticmethod
    def _write_log_header(path: Path, command: tuple[str, ...], cwd: Path) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as log:
            log.write(f"command={subprocess.list2cmdline(command)}\n")
            log.write(f"cwd={cwd}\n")
            log.flush()
