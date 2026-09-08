"""Project-local Chinese descriptions for custom Pose2Sim parameters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from app.io.atomic import AtomicJsonStore


class CustomHelpStore:
    _RELATIVE_PATH = Path("config") / "parameter_help.zh.json"

    @classmethod
    def load(cls, project_root: Path) -> dict[str, str]:
        path = Path(project_root) / cls._RELATIVE_PATH
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"中文参数说明文件无法读取：{path}") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(description, str)
            for key, description in value.items()
        ):
            raise ValueError(f"中文参数说明必须是字符串映射：{path}")
        return dict(value)

    @classmethod
    def save(cls, project_root: Path, values: Mapping[str, str]) -> None:
        normalized = {
            str(key).strip(): str(description).strip()
            for key, description in values.items()
            if str(key).strip() and str(description).strip()
        }
        AtomicJsonStore.replace(Path(project_root) / cls._RELATIVE_PATH, normalized)
