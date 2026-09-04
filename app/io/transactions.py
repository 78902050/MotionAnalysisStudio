"""Recoverable multi-file transactions for project-owned files."""

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .jsonl import JsonlStore


_TRANSACTION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_TERMINAL_STATUSES = {"completed", "rolled_back"}


def _project_path(root: Path, relative: str | Path) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise ValueError("transaction targets must be project-relative")
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("transaction target escapes the project root")
    return resolved


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class _PreparedFile:
    target: str
    staged: str
    backup: str
    existed: bool

    def as_record(self) -> dict[str, object]:
        return {
            "target": self.target,
            "staged": self.staged,
            "backup": self.backup,
            "existed": self.existed,
        }


class ProjectTransaction:
    """Stage project file replacements and make interrupted commits recoverable."""

    def __init__(self, root: Path, transaction_id: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.transaction_id = transaction_id or f"tx-{uuid4().hex}"
        if not _TRANSACTION_ID.fullmatch(self.transaction_id):
            raise ValueError("transaction_id contains unsupported characters")
        self.store = JsonlStore(self.root / "transactions.jsonl")
        self.workspace = self.root / "transactions" / self.transaction_id
        self._files: list[_PreparedFile] = []
        self._targets: set[str] = set()
        self._committed = False

    def prepare_json(
        self, target: str | Path, data: object, *, allow_nan: bool = False
    ) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=allow_nan) + "\n"
        self.prepare_bytes(target, payload.encode("utf-8"))

    def prepare_bytes(self, target: str | Path, data: bytes) -> None:
        if self._committed:
            raise RuntimeError("transaction is already committed")
        target_path = _project_path(self.root, target)
        relative_target = target_path.relative_to(self.root).as_posix()
        if relative_target in self._targets:
            raise ValueError(f"transaction target prepared twice: {relative_target}")

        index = len(self._files)
        staged_path = self.workspace / "staged" / f"{index}.new"
        backup_path = self.workspace / "backups" / f"{index}.old"
        _write_bytes(staged_path, bytes(data))
        existed = target_path.is_file()
        if existed:
            _write_bytes(backup_path, target_path.read_bytes())
        prepared = _PreparedFile(
            target=relative_target,
            staged=staged_path.relative_to(self.root).as_posix(),
            backup=backup_path.relative_to(self.root).as_posix(),
            existed=existed,
        )
        self._files.append(prepared)
        self._targets.add(relative_target)

    def commit(self) -> str:
        if self._committed:
            raise RuntimeError("transaction is already committed")
        self.store.append(
            {
                "transaction_id": self.transaction_id,
                "status": "prepared",
                "files": [item.as_record() for item in self._files],
            }
        )
        for item in self._files:
            target = _project_path(self.root, item.target)
            staged = _project_path(self.root, item.staged)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            self.store.append(
                {
                    "transaction_id": self.transaction_id,
                    "status": "file_replaced",
                    "target": item.target,
                }
            )
        self.store.append({"transaction_id": self.transaction_id, "status": "completed"})
        self._committed = True
        shutil.rmtree(self.workspace, ignore_errors=True)
        return self.transaction_id


class TransactionRecovery:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.store = JsonlStore(self.root / "transactions.jsonl")

    def recover_incomplete(self) -> list[str]:
        records, errors = self.store.read()
        if errors:
            raise ValueError("invalid transaction journal: " + "; ".join(errors))

        latest: dict[str, str] = {}
        order: list[str] = []
        for record in records:
            transaction_id = record.get("transaction_id")
            status = record.get("status")
            if not isinstance(transaction_id, str) or not transaction_id.strip():
                raise ValueError("transaction journal record has no transaction_id")
            if not isinstance(status, str) or not status.strip():
                raise ValueError(f"transaction {transaction_id} has no status")
            if transaction_id not in latest:
                order.append(transaction_id)
            latest[transaction_id] = status
        return [
            transaction_id
            for transaction_id in order
            if latest[transaction_id] not in _TERMINAL_STATUSES
        ]

    def recover_all(self) -> list[str]:
        records, errors = self.store.read()
        if errors:
            raise ValueError("invalid transaction journal: " + "; ".join(errors))

        prepared: dict[str, list[dict[str, object]]] = {}
        latest: dict[str, str] = {}
        order: list[str] = []
        for record in records:
            transaction_id = record.get("transaction_id")
            status = record.get("status")
            if not isinstance(transaction_id, str) or not transaction_id.strip():
                raise ValueError("transaction journal record has no transaction_id")
            if not isinstance(status, str) or not status.strip():
                raise ValueError(f"transaction {transaction_id} has no status")
            if transaction_id not in latest:
                order.append(transaction_id)
            latest[transaction_id] = status
            if status == "prepared":
                files = record.get("files")
                if not isinstance(files, list):
                    raise ValueError(f"transaction {transaction_id} has no prepared file list")
                prepared[transaction_id] = files

        recovered: list[str] = []
        for transaction_id in order:
            if latest[transaction_id] in _TERMINAL_STATUSES:
                continue
            files = prepared.get(transaction_id)
            if files is None:
                continue
            self._rollback(transaction_id, files)
            recovered.append(transaction_id)
        return recovered

    def _rollback(self, transaction_id: str, files: list[dict[str, object]]) -> None:
        for item in files:
            target_value = item.get("target")
            backup_value = item.get("backup")
            existed = item.get("existed")
            if not isinstance(target_value, str) or not isinstance(backup_value, str):
                raise ValueError(f"transaction {transaction_id} has an invalid file record")
            if not isinstance(existed, bool):
                raise ValueError(f"transaction {transaction_id} has no original file state")
            target = _project_path(self.root, target_value)
            if existed:
                backup = _project_path(self.root, backup_value)
                if not backup.is_file():
                    raise ValueError(
                        f"transaction {transaction_id} backup is missing: {backup_value}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{target.name}.", suffix=".restore", dir=target.parent
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(backup.read_bytes())
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_name, target)
                except BaseException:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
                    raise
            elif target.exists():
                target.unlink()
        self.store.append({"transaction_id": transaction_id, "status": "rolled_back"})
        shutil.rmtree(self.root / "transactions" / transaction_id, ignore_errors=True)
