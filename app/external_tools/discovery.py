"""Resolve user-selected installation folders into runnable tool entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolInstallation:
    installation_directory: Path
    executable: Path


class ExternalToolDiscovery:
    @classmethod
    def resolve_pose2sim(cls, selected: Path) -> ToolInstallation:
        selected = Path(selected).resolve()
        for root in cls._candidate_roots(selected):
            for python in (root / "python.exe", root / "Scripts" / "python.exe"):
                if not python.is_file():
                    continue
                environment = (
                    python.parent.parent
                    if python.parent.name.casefold() == "scripts"
                    else python.parent
                )
                package = environment / "Lib" / "site-packages" / "Pose2Sim" / "Pose2Sim.py"
                selected_package = selected / "Pose2Sim.py" if selected.is_dir() else None
                if package.is_file() or (selected_package is not None and selected_package.is_file()):
                    return ToolInstallation(environment.resolve(), python.resolve())
        raise ValueError(
            f"Pose2Sim 安装目录中未找到可用的 Python 环境：{selected}；"
            "请选择虚拟环境根目录、Scripts 目录或 Pose2Sim 包目录"
        )

    @classmethod
    def resolve_caliscope(cls, selected: Path) -> ToolInstallation:
        selected = Path(selected).resolve()
        if selected.is_file() and selected.name.casefold() == "caliscope.exe":
            root = (
                selected.parent.parent
                if selected.parent.name.casefold() == "scripts"
                else selected.parent
            )
            return ToolInstallation(root.resolve(), selected)
        for root in cls._candidate_roots(selected):
            for executable in (root / "caliscope.exe", root / "Scripts" / "caliscope.exe"):
                if executable.is_file():
                    environment = (
                        executable.parent.parent
                        if executable.parent.name.casefold() == "scripts"
                        else executable.parent
                    )
                    return ToolInstallation(environment.resolve(), executable.resolve())
        raise ValueError(
            f"Caliscope 安装目录中未找到 caliscope.exe：{selected}；"
            "请选择虚拟环境根目录或 Scripts 目录"
        )

    @staticmethod
    def _candidate_roots(selected: Path) -> tuple[Path, ...]:
        origin = selected.parent if selected.is_file() else selected
        candidates: list[Path] = []
        for path in (origin, *tuple(origin.parents)[:4]):
            if path not in candidates:
                candidates.append(path)
        return tuple(candidates)
