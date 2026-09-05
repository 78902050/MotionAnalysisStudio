"""Read synchronization mappings from project data, never camera-name branches."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.project.manager import ProjectManager

from .model import FrameMapping, SynchronizationIssue, SynchronizationReport
from .overrides import SynchronizationOverrideStore


class SynchronizationAnalyzer:
    def __init__(self) -> None:
        self._mappings: dict[tuple[str, int], FrameMapping] = {}
        self._offset_ranges: dict[str, list[tuple[int, int | None, int, str]]] = {}
        self._override_mappings: dict[tuple[str, int], FrameMapping] = {}
        self._override_offset_ranges: dict[str, list[tuple[int, int | None, int, str]]] = {}
        self._overrides = {}
        self._trust: dict[str, str] = {}
        self._issues: tuple[SynchronizationIssue, ...] = ()
        self._project: ProjectManager | None = None

    def analyze(self, project: ProjectManager) -> SynchronizationReport:
        self._project = project
        self._mappings.clear()
        self._offset_ranges.clear()
        self._override_mappings.clear()
        self._override_offset_ranges.clear()
        self._trust.clear()
        self._issues = ()
        path = project.root / "synchronization" / "mapping.json"
        issues: list[SynchronizationIssue] = []
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                issues.append(SynchronizationIssue("blocking", f"同步映射文件不可读：{exc}"))
                value = None
            if value is not None and not isinstance(value, dict):
                issues.append(SynchronizationIssue("blocking", "同步映射根节点必须是对象"))
            elif isinstance(value, dict):
                self._read_frame_mappings(value.get("mappings"), path, issues)
                self._read_offsets(value.get("offsets"), path, issues)
        else:
            inferred = self._read_filename_offsets(project, issues)

        try:
            overrides = SynchronizationOverrideStore(project.root).load()
        except (OSError, ValueError) as exc:
            issues.append(SynchronizationIssue("warning", f"人工同步 override 不可读：{exc}"))
            overrides = ()
        self._overrides = {item.camera: item for item in overrides}
        for override in overrides:
            if override.frame_delta is not None:
                self._trust[override.camera] = "confirmed_constant_offset"
            elif override.mapping_path is not None:
                self._load_override_mapping(override.camera, override.mapping_path, issues)
        for item in project.manifest.get("cameras", []):
            if isinstance(item, dict) and isinstance(item.get("camera_id"), str):
                self._trust.setdefault(item["camera_id"], "unavailable")
        if not any(
            trust in {"verified_mapping", "confirmed_constant_offset", "filename_candidate"}
            for trust in self._trust.values()
        ):
            issues.append(SynchronizationIssue("blocking", f"同步映射文件不存在或不可用：{path}"))
        self._issues = tuple(issues)
        return SynchronizationReport(
            tuple(self._mappings.values()),
            self._issues,
            dict(self._trust),
        )

    def mapping(self, camera: str, synchronized_frame: int) -> FrameMapping:
        if not camera.strip():
            raise ValueError("camera must not be empty")
        if synchronized_frame < 0:
            raise ValueError("synchronized_frame must be non-negative")
        override = self._overrides.get(camera)
        if override is not None and override.frame_delta is not None:
            return FrameMapping(
                camera,
                "raw",
                "synchronized",
                synchronized_frame + override.frame_delta,
                synchronized_frame,
                "offset",
                None,
                override.source,
            )
        if override is not None and override.mapping_path is not None:
            exact = self._override_mappings.get((camera, synchronized_frame))
            if exact is not None:
                return exact
            for start, end, delta, source in self._override_offset_ranges.get(camera, []):
                if synchronized_frame >= start and (end is None or synchronized_frame <= end):
                    return FrameMapping(
                        camera,
                        "raw",
                        "synchronized",
                        synchronized_frame + delta,
                        synchronized_frame,
                        "offset",
                        None,
                        source,
                    )
            raise KeyError(f"no verified override mapping for {camera} frame {synchronized_frame}")
        exact = self._mappings.get((camera, synchronized_frame))
        if exact is not None:
            return exact
        for start, end, delta, source in self._offset_ranges.get(camera, []):
            if synchronized_frame >= start and (end is None or synchronized_frame <= end):
                source_frame = synchronized_frame + delta
                if source_frame < 0:
                    raise ValueError(f"mapping produces a negative raw frame: {camera} {synchronized_frame}")
                return FrameMapping(
                    camera,
                    "raw",
                    "synchronized",
                    source_frame,
                    synchronized_frame,
                    "offset",
                    None,
                    source,
                )
        raise KeyError(f"no synchronization mapping for {camera} frame {synchronized_frame}")

    def _read_frame_mappings(self, records: object, path: Path, issues: list[SynchronizationIssue]) -> None:
        if records is None:
            return
        if not isinstance(records, list):
            issues.append(SynchronizationIssue("blocking", "同步 mappings 必须是列表"))
            return
        for item in records:
            if not isinstance(item, dict):
                issues.append(SynchronizationIssue("warning", "忽略无效同步 mapping 记录"))
                continue
            try:
                camera = str(item["camera"])
                target = int(item["target_frame"])
                source = int(item["source_frame"])
                method = str(item.get("method", "table"))
                mapping = FrameMapping(
                    camera,
                    str(item.get("source_timeline", "raw")),
                    str(item.get("target_timeline", "synchronized")),
                    source,
                    target,
                    method,
                    float(item["confidence"]) if item.get("confidence") is not None else None,
                    str(item.get("source", path)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(SynchronizationIssue("warning", f"忽略无效同步 mapping：{exc}"))
                continue
            self._mappings[(mapping.camera, mapping.target_frame)] = mapping
            self._trust[mapping.camera] = "verified_mapping"

    def _read_offsets(self, records: object, path: Path, issues: list[SynchronizationIssue]) -> None:
        if records is None:
            return
        if isinstance(records, dict):
            records = [
                {"camera": camera, "frame_delta": delta, "source": str(path)}
                for camera, delta in records.items()
            ]
        if not isinstance(records, list):
            issues.append(SynchronizationIssue("blocking", "同步 offsets 必须是列表或对象"))
            return
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                camera = str(item["camera"])
                start = int(item.get("start_frame", 0))
                end_value = item.get("end_frame")
                end = int(end_value) if end_value is not None else None
                delta = int(item["frame_delta"])
                if start < 0 or (end is not None and end < start):
                    raise ValueError("invalid offset frame range")
                source = str(item.get("source", path))
                self._offset_ranges.setdefault(camera, []).append((start, end, delta, source))
                self._trust[camera] = "verified_mapping"
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(SynchronizationIssue("warning", f"忽略无效同步 offset：{exc}"))

    def _read_filename_offsets(self, project: ProjectManager, issues: list[SynchronizationIssue]) -> bool:
        raw_root = project.root / "pose"
        sync_root = project.root / "pose-sync"
        cameras: set[str] = set()
        for item in project.manifest.get("cameras", []):
            if isinstance(item, dict) and isinstance(item.get("camera_id"), str):
                cameras.add(item["camera_id"])
        for root in (raw_root, sync_root):
            if root.is_dir():
                cameras.update(
                    item.name.removesuffix("_json")
                    for item in root.iterdir()
                    if item.is_dir() and item.name.endswith("_json")
                )
        inferred = False
        for camera in sorted(cameras):
            raw_dir = raw_root / f"{camera}_json"
            sync_dir = sync_root / f"{camera}_json"
            raw_frames = self._filename_frames(raw_dir)
            sync_frames = self._filename_frames(sync_dir)
            if not raw_frames or not sync_frames:
                continue
            delta = min(raw_frames) - min(sync_frames)
            shifted = {frame + delta for frame in sync_frames}
            if not shifted.issubset(raw_frames):
                continue
            source = f"{raw_dir} and {sync_dir} filename ranges"
            self._trust.setdefault(camera, "filename_candidate")
            inferred = True
        if inferred:
            issues.append(SynchronizationIssue("warning", "同步映射由 pose 与 pose-sync 文件名范围推导"))
        return inferred

    def _load_override_mapping(
        self,
        camera: str,
        mapping_path: Path,
        issues: list[SynchronizationIssue],
    ) -> None:
        path = Path(mapping_path)
        if not path.is_absolute() and self._project is not None:
            path = self._project.root / path
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(SynchronizationIssue("blocking", f"人工映射文件不可读：{exc}", camera))
            self._trust[camera] = "unavailable"
            return
        if not isinstance(value, dict):
            issues.append(SynchronizationIssue("blocking", "人工映射文件根节点必须是对象", camera))
            self._trust[camera] = "unavailable"
            return
        found = False
        records = value.get("mappings")
        if isinstance(records, list):
            for item in records:
                if not isinstance(item, dict) or item.get("camera") != camera:
                    continue
                try:
                    mapping = FrameMapping(
                        camera,
                        str(item.get("source_timeline", "raw")),
                        str(item.get("target_timeline", "synchronized")),
                        int(item["source_frame"]),
                        int(item["target_frame"]),
                        str(item.get("method", "table")),
                        float(item["confidence"]) if item.get("confidence") is not None else None,
                        str(path),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    issues.append(SynchronizationIssue("warning", f"忽略无效人工 mapping：{exc}", camera))
                    continue
                self._override_mappings[(camera, mapping.target_frame)] = mapping
                found = True
        offsets = value.get("offsets")
        if isinstance(offsets, dict):
            offsets = [{"camera": name, "frame_delta": delta} for name, delta in offsets.items()]
        if isinstance(offsets, list):
            for item in offsets:
                if not isinstance(item, dict) or item.get("camera") != camera:
                    continue
                try:
                    start = int(item.get("start_frame", 0))
                    end_value = item.get("end_frame")
                    end = int(end_value) if end_value is not None else None
                    delta = int(item["frame_delta"])
                    if start < 0 or (end is not None and end < start):
                        raise ValueError("invalid offset frame range")
                except (KeyError, TypeError, ValueError) as exc:
                    issues.append(SynchronizationIssue("warning", f"忽略无效人工 offset：{exc}", camera))
                    continue
                self._override_offset_ranges.setdefault(camera, []).append(
                    (start, end, delta, str(path))
                )
                found = True
        self._trust[camera] = "verified_mapping" if found else "unavailable"
        if not found:
            issues.append(SynchronizationIssue("blocking", "人工映射文件没有该相机的有效映射", camera))

    @staticmethod
    def _filename_frames(directory: Path) -> set[int]:
        if not directory.is_dir():
            return set()
        result: set[int] = set()
        for item in directory.glob("*.json"):
            match = re.search(r"_(\d+)\.json$", item.name)
            if match:
                result.add(int(match.group(1)))
        return result
