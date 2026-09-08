"""Plan and execute imports of project-managed analysis videos."""

from __future__ import annotations

import re
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from app.project.manager import ProjectManager
from app.tasks.base import CancellationToken


_NUMERIC_CAMERA = re.compile(r"(?:camera|cam)?0*(\d+)")


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def normalize_camera_name(name: str) -> str:
    compact = re.sub(r"[\s_-]+", "", name.strip().casefold())
    numeric = _NUMERIC_CAMERA.fullmatch(compact)
    if numeric:
        return f"cam{int(numeric.group(1))}"
    return compact


def _camera_destination(project: ProjectManager, camera: str, suffix: str) -> Path:
    videos_root = (project.root / "videos").resolve()
    destination = (videos_root / f"{camera}{suffix}").resolve()
    if destination.parent != videos_root:
        raise ValueError(f"unsafe camera ID for video destination: {camera!r}")
    return destination


def _mark_duplicate_conflicts(
    items: tuple[VideoImportItem, ...],
) -> tuple[VideoImportItem, ...]:
    counts = Counter(str(item.destination).casefold() for item in items)
    return tuple(
        replace(item, conflict=True)
        if counts[str(item.destination).casefold()] > 1 and not item.conflict
        else item
        for item in items
    )


@dataclass(frozen=True)
class VideoImportItem:
    source: Path
    destination: Path
    camera: str | None
    match_method: str
    conflict: bool


@dataclass(frozen=True)
class VideoImportPlan:
    items: tuple[VideoImportItem, ...]
    unmatched_files: tuple[Path, ...]
    requires_confirmation: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class VideoImportResult:
    imported: tuple[Path, ...]
    bound_cameras: tuple[str, ...]
    skipped: tuple[Path, ...]


class VideoImportService:
    _VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
    _DERIVED_TOKENS = ("_pose", "_sync", "_tracked", "_calibration")

    @classmethod
    def plan(
        cls, project: ProjectManager, paths: Iterable[Path]
    ) -> VideoImportPlan:
        sources = tuple(Path(path).resolve() for path in paths)
        for source in sources:
            if not source.is_file():
                raise FileNotFoundError(f"video file not found: {source}")
        candidates = tuple(
            source
            for source in sources
            if source.suffix.casefold() in cls._VIDEO_SUFFIXES
            and not any(token in source.stem.casefold() for token in cls._DERIVED_TOKENS)
        )
        records = project.manifest.get("cameras", [])
        cameras = tuple(
            str(record["camera_id"])
            for record in records
            if isinstance(record, dict) and str(record.get("camera_id", "")).strip()
        ) if isinstance(records, list) else ()

        if not cameras:
            items = tuple(
                VideoImportItem(
                    source=source,
                    destination=project.root / "videos" / source.name,
                    camera=source.stem,
                    match_method="new_camera",
                    conflict=(project.root / "videos" / source.name).exists(),
                )
                for source in candidates
            )
            return VideoImportPlan(
                items=_mark_duplicate_conflicts(items),
                unmatched_files=tuple(source for source in sources if source not in candidates),
                requires_confirmation=False,
                warnings=(),
            )

        normalized_cameras: dict[str, list[str]] = {}
        for camera in cameras:
            normalized_cameras.setdefault(normalize_camera_name(camera), []).append(camera)
        normalized_sources: dict[str, list[Path]] = {}
        for source in candidates:
            normalized_sources.setdefault(normalize_camera_name(source.stem), []).append(source)

        items: list[VideoImportItem] = []
        for source in candidates:
            normalized = normalize_camera_name(source.stem)
            matches = normalized_cameras.get(normalized, [])
            if len(matches) != 1 or len(normalized_sources[normalized]) != 1:
                continue
            camera = matches[0]
            destination = _camera_destination(project, camera, source.suffix)
            items.append(
                VideoImportItem(
                    source=source,
                    destination=destination,
                    camera=camera,
                    match_method="semantic",
                    conflict=destination.exists(),
                )
            )

        used = {item.source for item in items}
        used_cameras = {item.camera for item in items}
        remaining_sources = sorted(
            (source for source in candidates if source not in used),
            key=lambda source: _natural_key(source.name),
        )
        remaining_cameras = sorted(
            (camera for camera in cameras if camera not in used_cameras),
            key=_natural_key,
        )
        ordered = bool(remaining_sources) and len(remaining_sources) == len(remaining_cameras)
        if ordered:
            for source, camera in zip(remaining_sources, remaining_cameras, strict=True):
                destination = _camera_destination(project, camera, source.suffix)
                items.append(
                    VideoImportItem(
                        source=source,
                        destination=destination,
                        camera=camera,
                        match_method="ordered",
                        conflict=destination.exists(),
                    )
                )
            used.update(remaining_sources)

        warnings = (
            ("Unmatched video files were not assigned to existing cameras.",)
            if remaining_sources and not ordered
            else ()
        )

        return VideoImportPlan(
            items=_mark_duplicate_conflicts(tuple(items)),
            unmatched_files=tuple(source for source in sources if source not in used),
            requires_confirmation=ordered,
            warnings=warnings,
        )

    @classmethod
    def execute(
        cls,
        project: ProjectManager,
        plan: VideoImportPlan,
        *,
        replace_existing: bool,
        token: CancellationToken,
        progress: Callable[[int, int, Path], None] | None = None,
    ) -> VideoImportResult:
        imported: list[Path] = []
        bound_cameras: list[str] = []
        skipped: list[Path] = []
        total = len(plan.items)

        for completed, item in enumerate(plan.items, start=1):
            token.raise_if_cancelled()
            if item.destination.exists() and not replace_existing:
                skipped.append(item.destination)
                if item.camera is not None:
                    bound_cameras.append(item.camera)
                if progress is not None:
                    progress(completed, total, item.source)
                continue

            item.destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{item.destination.name}.",
                suffix=".tmp",
                dir=item.destination.parent,
            )
            try:
                with item.source.open("rb") as source_handle, os.fdopen(
                    descriptor, "wb"
                ) as destination_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        destination_handle.write(chunk)
                        token.raise_if_cancelled()
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
                token.raise_if_cancelled()
                os.replace(temporary_name, item.destination)
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise

            imported.append(item.destination)
            if item.camera is not None:
                bound_cameras.append(item.camera)
            if progress is not None:
                progress(completed, total, item.source)

        if bound_cameras:
            records = project.manifest.setdefault("cameras", [])
            for item in plan.items:
                if item.camera is None or item.destination not in imported + skipped:
                    continue
                record = next(
                    (
                        candidate
                        for candidate in records
                        if isinstance(candidate, dict)
                        and candidate.get("camera_id") == item.camera
                    ),
                    None,
                )
                if record is None:
                    record = {"camera_id": item.camera}
                    records.append(record)
                record["video_path"] = item.destination.relative_to(project.root).as_posix()
            project.save_manifest()

        return VideoImportResult(
            imported=tuple(imported),
            bound_cameras=tuple(bound_cameras),
            skipped=tuple(skipped),
        )
