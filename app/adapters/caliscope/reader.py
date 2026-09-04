"""Read-only Caliscope export reader."""

import json
import tomllib
from pathlib import Path
from typing import Any


class CaliscopeReader:
    def __init__(self, source: Path) -> None:
        self.source = Path(source)

    def read(self) -> dict[str, Any]:
        if not self.source.is_file():
            raise FileNotFoundError(f"Caliscope source not found: {self.source}")
        raw = self.source.read_bytes()
        suffix = self.source.suffix.lower()
        try:
            if suffix == ".json":
                value = json.loads(raw.decode("utf-8"))
            elif suffix == ".toml":
                value = tomllib.loads(raw.decode("utf-8"))
            else:
                raise ValueError(f"unsupported Caliscope calibration format: {self.source}")
        except (UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"invalid Caliscope calibration file: {self.source}") from exc
        if not isinstance(value, dict):
            raise ValueError("Caliscope calibration root must be an object")
        return value
