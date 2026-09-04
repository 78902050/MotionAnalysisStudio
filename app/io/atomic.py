"""Atomic JSON replacement and exclusive first-backup operations."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AtomicJsonStore:
    @staticmethod
    def replace(path: Path, data: object, *, allow_nan: bool = False) -> None:
        path = Path(path)
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=allow_nan) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def backup_once(source: Path, backup: Path) -> bool:
        source = Path(source)
        backup = Path(backup)
        data = source.read_bytes()
        backup.parent.mkdir(parents=True, exist_ok=True)
        try:
            with backup.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False
