"""Launch and diagnose optional desktop analysis tools."""

from .launcher import ExternalProcessHandle, ExternalToolLaunchError, ExternalToolLauncher
from .model import build_caliscope_command
from .discovery import ExternalToolDiscovery, ToolInstallation

__all__ = [
    "ExternalProcessHandle",
    "ExternalToolLaunchError",
    "ExternalToolLauncher",
    "build_caliscope_command",
    "ExternalToolDiscovery",
    "ToolInstallation",
]
