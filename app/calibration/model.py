"""Domain records for calibration fingerprints and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CalibrationSeverity = Literal["info", "warning", "blocking"]


@dataclass(frozen=True)
class CalibrationFingerprint:
    path: object
    fingerprint: str
    size: int
    modified_at: str
    camera_ids: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationIssue:
    severity: CalibrationSeverity
    message: str
    camera_id: str | None = None


@dataclass(frozen=True)
class CalibrationCameraReport:
    camera_id: str
    reprojection_error: float | None
    coverage: float | None


@dataclass(frozen=True)
class CalibrationReport:
    active_path: object | None
    fingerprint: str | None
    camera_ids: tuple[str, ...]
    cameras: tuple[CalibrationCameraReport, ...]
    issues: tuple[CalibrationIssue, ...]
    generated_at: str
