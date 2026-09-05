"""Immutable summaries for already-processed motion-analysis trials."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ConfigState = Literal["missing", "empty", "valid", "invalid"]


@dataclass(frozen=True)
class ArtifactSummary:
    pose_2d: int
    pose_sync: int
    pose_associated: int
    trc: tuple[Path, ...]
    kinematics: tuple[Path, ...]

    @property
    def has_results(self) -> bool:
        return bool(
            self.pose_2d
            or self.pose_sync
            or self.pose_associated
            or self.trc
            or self.kinematics
        )


@dataclass(frozen=True)
class TrialCandidate:
    root: Path
    cameras: tuple[str, ...]
    artifacts: ArtifactSummary
    calibration_path: Path | None
    config_path: Path | None
    config_state: ConfigState
    source_videos: tuple[Path, ...]
    derived_videos: tuple[Path, ...]

    @property
    def has_video(self) -> bool:
        return bool(self.source_videos or self.derived_videos)

