"""Motion Analysis Studio application package."""

from importlib.util import find_spec

__all__ = ["project_version", "runtime_capabilities"]

__version__ = "0.1.0"


def project_version() -> str:
    """Return the application package version."""

    return __version__


def runtime_capabilities() -> dict[str, bool]:
    """Report optional runtime components available to the application."""

    modules = {
        "pyside6": "PySide6",
        "opencv": "cv2",
        "numpy": "numpy",
        "pyinstaller": "PyInstaller",
    }
    capabilities = {"python": True}
    for name, module in modules.items():
        try:
            capabilities[name] = find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            capabilities[name] = False
    return capabilities
