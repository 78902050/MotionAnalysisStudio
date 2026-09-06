"""Discover Pose2Sim TRC/C3D outputs for playback."""

from __future__ import annotations

import re
from pathlib import Path

from .model import TrajectorySource


_POSE2SIM_TRAJECTORY = re.compile(
    r"^(?P<trial>.+)_P(?P<person>\d+)_(?P<first>\d+)-(?P<last>\d+)(?:_(?P<suffix>.+))?$",
    re.IGNORECASE,
)


class TrajectoryCatalog:
    @classmethod
    def scan(cls, project_root: Path) -> tuple[TrajectorySource, ...]:
        directory = Path(project_root).resolve() / "pose-3d"
        if not directory.is_dir():
            return ()
        sources: list[TrajectorySource] = []
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.casefold() not in {".trc", ".c3d"}:
                continue
            match = _POSE2SIM_TRAJECTORY.fullmatch(path.stem)
            if match is None:
                continue
            sources.append(
                TrajectorySource(
                    path.resolve(),
                    path.suffix.casefold().removeprefix("."),  # type: ignore[arg-type]
                    match.group("trial"),
                    f"P{int(match.group('person'))}",
                    cls._variant(match.group("suffix")),
                )
            )
        return tuple(sorted(sources, key=cls._sort_key))

    @staticmethod
    def _variant(suffix: str | None) -> str:
        if not suffix:
            return "raw"
        normalized = suffix.strip().casefold()
        if normalized.startswith("filt_"):
            normalized = normalized.removeprefix("filt_")
        return normalized

    @staticmethod
    def _sort_key(source: TrajectorySource) -> tuple[object, ...]:
        person_number = int(source.person_id[1:])
        variant_rank = 0 if source.variant == "raw" else 1
        format_rank = 0 if source.format == "trc" else 1
        return (
            source.trial_id.casefold(),
            person_number,
            variant_rank,
            source.variant.casefold(),
            format_rank,
            source.path.name.casefold(),
        )
