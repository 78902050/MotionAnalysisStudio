"""Launch and diagnose optional desktop analysis tools."""

from .launcher import ExternalProcessHandle, ExternalToolLaunchError, ExternalToolLauncher
from .model import build_caliscope_command

__all__ = [
    "ExternalProcessHandle",
    "ExternalToolLaunchError",
    "ExternalToolLauncher",
    "build_caliscope_command",
]
