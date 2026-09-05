"""Commands for optional external desktop tools."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def build_caliscope_command(
    workspace: Path,
    configured_executable: Path | str | None = None,
) -> tuple[str, ...]:
    workspace = Path(workspace)
    executable = str(configured_executable).strip() if configured_executable else ""
    if not executable:
        executable = os.environ.get("CALISCOPE_EXECUTABLE", "").strip()
    if not executable:
        executable = shutil.which("caliscope") or ""
    if not executable:
        sibling = Path(sys.executable).with_name("caliscope.exe" if os.name == "nt" else "caliscope")
        executable = str(sibling) if sibling.is_file() else "caliscope"
    return executable, "--workspace", str(workspace)
