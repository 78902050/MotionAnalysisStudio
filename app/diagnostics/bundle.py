"""Create small, redacted diagnostic archives without copying project inputs."""

from __future__ import annotations

import json
import re
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any


_REQUIRED_MODULES = {
    "PySide6": "PySide6",
    "NumPy": "numpy",
    "OpenCV": "cv2",
    "PyInstaller": "PyInstaller",
    "Pose2Sim": "Pose2Sim",
    "Caliscope": "caliscope",
}
# The one-file desktop bundle embeds the UI runtime. Analysis engines and the
# build tool remain external capabilities and are checked by the full install
# validation path instead of being falsely required by the frozen smoke test.
_EMBEDDED_MODULES = {"PySide6": "PySide6"}
_PACKAGE_NAMES = {
    "PySide6": "PySide6",
    "NumPy": "numpy",
    "OpenCV": "opencv-python",
    "PyInstaller": "pyinstaller",
    "Pose2Sim": "Pose2Sim",
    "Caliscope": "caliscope",
}
_MAX_LOG_BYTES = 2 * 1024 * 1024
_WINDOWS_PATH = re.compile(r"(?i)[a-z]:[\\/][^\r\n\"']+")


def validate_installation(include_external: bool = True) -> list[str]:
    """Return actionable missing-capability messages; an empty list means ready."""

    issues: list[str] = []
    if sys.version_info < (3, 12):
        issues.append(f"Python 3.12 or newer is required; found {sys.version.split()[0]}")
    required = _REQUIRED_MODULES if include_external else _EMBEDDED_MODULES
    for label, module_name in required.items():
        try:
            available = find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            issues.append(f"missing runtime capability: {label} ({module_name})")
    return issues


class DiagnosticBundle:
    """Write only redacted diagnostics and small logs into a zip archive."""

    def create(self, project, destination: Path) -> Path:
        root = Path(project.root).resolve()
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination / "diagnostics.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)

        manifest = _redact_value(dict(project.manifest))
        manifest_text = _redact_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", root)
        runtime = {
            "python": sys.version.split()[0],
            "capabilities": {label: _has_module(module) for label, module in _REQUIRED_MODULES.items()},
            "versions": {label: _package_version(package) for label, package in _PACKAGE_NAMES.items()},
        }
        entries: dict[str, str] = {
            "manifest.json": manifest_text,
            "diagnostics/runtime.json": json.dumps(runtime, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            "diagnostics/README.txt": "This bundle contains redacted diagnostics only; project inputs are excluded.\n",
        }
        logs_root = root / "logs"
        if logs_root.is_dir():
            for log_path in sorted(logs_root.glob("*.log")):
                if not log_path.is_file() or log_path.stat().st_size > _MAX_LOG_BYTES:
                    continue
                text = log_path.read_text(encoding="utf-8", errors="replace")
                entries[f"diagnostics/logs/{log_path.name}"] = _redact_text(text, root)

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                archive.writestr(name, entries[name])
        return destination


def _has_module(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def _redact_value(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {str(name): _redact_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, key) for item in value]
    if isinstance(value, str) and any(token in key.lower() for token in ("path", "root", "directory", "filename", "video")):
        return "<redacted>"
    return value


def _redact_text(text: str, project_root: Path) -> str:
    redacted = text.replace(str(project_root), "<project-root>")
    return _WINDOWS_PATH.sub("<redacted-path>", redacted)
