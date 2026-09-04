"""Read-only Caliscope export reader."""

import json
from pathlib import Path
from typing import Any


class CaliscopeReader:
    def __init__(self, source: Path) -> None:
        self.source = Path(source)

    def read(self) -> dict[str, Any]:
        if not self.source.is_file():
            raise FileNotFoundError(f"Caliscope source not found: {self.source}")
        try:
            value = json.loads(self.source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Caliscope JSON: {self.source}") from exc
        if not isinstance(value, dict):
            raise ValueError("Caliscope JSON root must be an object")
        return value
