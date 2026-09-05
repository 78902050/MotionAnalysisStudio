"""Inspect and explicitly convert Caliscope's user settings encoding."""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CaliscopeSettingsInspection:
    path: Path
    exists: bool
    encoding: str | None
    valid: bool
    message: str


class CaliscopeSettingsDiagnostic:
    @staticmethod
    def default_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "caliscope" / "caliscope" / "settings.toml"

    @staticmethod
    def inspect(path: Path) -> CaliscopeSettingsInspection:
        path = Path(path)
        if not path.is_file():
            return CaliscopeSettingsInspection(path, False, None, False, "未找到 Caliscope 设置文件")
        try:
            data = path.read_bytes()
        except OSError as exc:
            return CaliscopeSettingsInspection(path, True, None, False, f"读取失败：{exc}")
        errors: list[str] = []
        for encoding in ("utf-8", "gb18030"):
            try:
                text = data.decode(encoding)
                tomllib.loads(text)
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                errors.append(f"{encoding}: {exc}")
                continue
            message = "设置文件为 UTF-8，可直接使用" if encoding == "utf-8" else "检测到 GB18030；建议备份后转换为 UTF-8"
            return CaliscopeSettingsInspection(path, True, encoding, True, message)
        return CaliscopeSettingsInspection(path, True, None, False, "设置文件无法解析：" + "；".join(errors))

    @staticmethod
    def convert_to_utf8(path: Path) -> Path:
        path = Path(path)
        inspection = CaliscopeSettingsDiagnostic.inspect(path)
        if not inspection.valid or inspection.encoding is None:
            raise ValueError(inspection.message)
        source = path.read_bytes()
        text = source.decode(inspection.encoding)
        tomllib.loads(text)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        with backup.open("xb") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            CaliscopeSettingsDiagnostic._replace_bytes(path, text.encode("utf-8"))
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        return backup

    @staticmethod
    def _replace_bytes(path: Path, data: bytes) -> None:
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
