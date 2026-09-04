"""Append-only UTF-8 JSONL storage with explicit corruption reporting."""

import json
from pathlib import Path


class JsonlStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, record: dict[str, object]) -> None:
        if not isinstance(record, dict):
            raise TypeError("JSONL records must be objects")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()

    def read(self) -> tuple[list[dict[str, object]], list[str]]:
        if not self.path.exists():
            return [], []
        records: list[dict[str, object]] = []
        errors: list[str] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            if not isinstance(value, dict):
                errors.append(f"line {line_number}: JSONL record must be an object")
                continue
            records.append(value)
        return records, errors
