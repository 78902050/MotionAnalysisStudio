"""Text-preserving validation and atomic saves for Pose2Sim Config.toml."""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


class ConfigSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class ConfigValidation:
    valid: bool
    message: str


@dataclass(frozen=True)
class ConfigSaveResult:
    changed: bool
    backup_path: Path | None
    reason: str


class ConfigDocument:
    def __init__(self, path: Path, text: str) -> None:
        self.path = Path(path)
        self._text = text

    @classmethod
    def open(cls, path: Path) -> "ConfigDocument":
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigSyntaxError(f"Config.toml 不是 UTF-8：{exc}") from exc
        return cls(path, text)

    @property
    def text(self) -> str:
        return self._text

    @staticmethod
    def validate(text: str) -> ConfigValidation:
        if not text.strip():
            return ConfigValidation(False, "Config.toml 为空，不能运行 Pose2Sim")
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return ConfigValidation(False, f"TOML 语法错误：{exc}")
        return ConfigValidation(True, "Config.toml 语法有效")

    def has_unsaved_changes(self, text: str) -> bool:
        return text != self._text

    def reload(self) -> str:
        try:
            text = self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigSyntaxError(f"Config.toml 不是 UTF-8：{exc}") from exc
        self._text = text
        return text

    def save(self, text: str, reason: str = "") -> ConfigSaveResult:
        validation = self.validate(text)
        if not validation.valid:
            raise ConfigSyntaxError(validation.message)
        if text == self._text and self.path.is_file():
            return ConfigSaveResult(False, None, reason)

        original = self.path.read_bytes() if self.path.is_file() else None
        backup_path = None
        if original is not None:
            backup_root = self.path.parent / "backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_path = backup_root / f"{stamp}-{uuid4().hex[:8]}-{self.path.name}"
            self._write_exclusive(backup_path, original)

        self._replace_bytes(self.path, text.encode("utf-8"))
        self._text = text
        return ConfigSaveResult(True, backup_path, reason)

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _replace_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            Path(temporary_name).unlink(missing_ok=True)
            raise
