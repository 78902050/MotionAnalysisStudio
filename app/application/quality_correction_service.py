"""Resolve quality issues into auditable, editable 2D correction sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.adapters.pose2sim.pose2d_repository import Pose2DRepository
from app.correction.session import CorrectionSession
from app.domain.addresses import CorrectionTarget, FrameAddress, PersonAddress
from app.domain.issues import QualityIssue
from app.pose_editor.model import PoseDocument
from app.project.manager import ProjectManager
from app.quality.model import QualityReport
from app.quality.report_store import QualityReportStore
from app.synchronization.analyzer import SynchronizationAnalyzer


@dataclass(frozen=True)
class CorrectionResolution:
    issue_id: str
    report_target: CorrectionTarget | None
    edit_target: CorrectionTarget | None
    synchronized_frame: int | None
    raw_frame: int | None
    mapping_source: str | None
    pose_path: Path | None
    keypoint_names: tuple[str, ...] | None = None
    blocker: str | None = None

    @property
    def can_edit(self) -> bool:
        return self.blocker is None and self.edit_target is not None and self.pose_path is not None


class QualityCorrectionService:
    def __init__(self, project: ProjectManager) -> None:
        self.project = project
        self.synchronization = SynchronizationAnalyzer()
        self.synchronization_report = self.synchronization.analyze(project)

    def load_report(self) -> QualityReport:
        return QualityReportStore(self.project).load_current()

    def timeline_bounds(self) -> tuple[int, int]:
        """Return the synchronized frame range supported by the current report."""
        try:
            report = self.load_report()
        except (OSError, ValueError, KeyError):
            return 0, 0
        frames = [
            issue.target.frame
            for issue in report.issues()
            if issue.target is not None
            and issue.target.timeline in {"synchronized", "pose2d", "pose3d"}
        ]
        metrics = report.metrics()
        for name in ("coverage_start_frame", "coverage_end_frame"):
            value = metrics.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                frames.append(value)
        return (min(frames), max(frames)) if frames else (0, 0)

    def raw_view_addresses(
        self,
        synchronized_frame: int,
        cameras: tuple[str, ...] | list[str],
    ) -> tuple[dict[str, FrameAddress], dict[str, str]]:
        addresses: dict[str, FrameAddress] = {}
        failures: dict[str, str] = {}
        for camera in cameras:
            try:
                mapping = self.synchronization.mapping(camera, synchronized_frame)
            except (KeyError, ValueError) as exc:
                failures[camera] = f"同步映射不可用：{exc}"
                continue
            addresses[camera] = FrameAddress(camera, "raw", mapping.source_frame)
        return addresses, failures

    def resolve_target(
        self,
        target: CorrectionTarget,
        *,
        issue_id: str = "direct-target",
    ) -> CorrectionResolution:
        if issue_id == "direct-target":
            try:
                matches = [
                    issue.issue_id
                    for issue in self.load_report().issues()
                    if self._report_target(issue) == target
                ]
            except (OSError, ValueError, KeyError):
                matches = []
            if len(matches) == 1:
                issue_id = matches[0]
        issue = QualityIssue(
            issue_id,
            "reprojection",
            "warning",
            target.address,
            target.person,
            target.keypoint,
            "二维修正定位",
        )
        return self.resolve_issue(issue)

    def resolve_issue(self, issue: QualityIssue) -> CorrectionResolution:
        report_target = self._report_target(issue)
        if report_target is None:
            return self._blocked(issue.issue_id, "质量问题缺少相机、人物或关节点定位信息")
        synchronized_frame = self._synchronized_frame(report_target.address)
        if synchronized_frame is None:
            return self._blocked(
                issue.issue_id,
                f"不支持从 {report_target.address.timeline} 时间轴反推同步帧",
                report_target,
            )
        try:
            mapping = self.synchronization.mapping(
                report_target.address.camera,
                synchronized_frame,
            )
        except (KeyError, ValueError) as exc:
            return self._blocked(
                issue.issue_id,
                f"同步帧无法映射到原视频帧：{exc}",
                report_target,
                synchronized_frame,
            )

        raw_person_index, person_blocker = self._raw_person_index(
            report_target.person,
            report_target.address.camera,
            synchronized_frame,
        )
        if person_blocker is not None:
            return self._blocked(
                issue.issue_id,
                person_blocker,
                report_target,
                synchronized_frame,
                mapping.source_frame,
                mapping.source,
            )
        assert raw_person_index is not None
        pose_path, keypoint_names, pose_blocker = self._pose_source(
            report_target,
            mapping.source_frame,
        )
        if pose_blocker is not None:
            return self._blocked(
                issue.issue_id,
                pose_blocker,
                report_target,
                synchronized_frame,
                mapping.source_frame,
                mapping.source,
                pose_path,
            )
        if pose_path is None:
            return self._blocked(
                issue.issue_id,
                f"缺少相机 {report_target.address.camera} 的可编辑二维 pose 文件",
                report_target,
                synchronized_frame,
                mapping.source_frame,
                mapping.source,
            )
        edit_target = CorrectionTarget(
            FrameAddress(report_target.address.camera, "raw", mapping.source_frame),
            PersonAddress(
                report_target.person.project_person_id,
                report_target.person.track_segment_id,
                raw_person_index,
            ),
            report_target.keypoint,
        )
        try:
            self._document(pose_path, keypoint_names).value_at(edit_target)
        except KeyError as exc:
            message = str(exc)
            subject = "关节点" if "keypoint" in message else "人物或帧"
            return self._blocked(
                issue.issue_id,
                f"无法在二维 pose 中定位{subject}：{exc}",
                report_target,
                synchronized_frame,
                mapping.source_frame,
                mapping.source,
                pose_path,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return self._blocked(
                issue.issue_id,
                f"二维 pose 文件不可读：{exc}",
                report_target,
                synchronized_frame,
                mapping.source_frame,
                mapping.source,
                pose_path,
            )
        return CorrectionResolution(
            issue.issue_id,
            report_target,
            edit_target,
            synchronized_frame,
            mapping.source_frame,
            mapping.source,
            pose_path,
            keypoint_names,
        )

    def create_session(self, resolution: CorrectionResolution) -> CorrectionSession:
        if not resolution.can_edit or resolution.edit_target is None or resolution.pose_path is None:
            raise ValueError(resolution.blocker or "该质量问题不可编辑")
        document = self._document(resolution.pose_path, resolution.keypoint_names)
        session = CorrectionSession(document, project_root=self.project.root)
        session.open((resolution.edit_target,), (resolution.issue_id,))
        return session

    @staticmethod
    def _report_target(issue: QualityIssue) -> CorrectionTarget | None:
        if issue.target is None or issue.person is None or issue.keypoint is None:
            return None
        return CorrectionTarget(issue.target, issue.person, issue.keypoint)

    @staticmethod
    def _synchronized_frame(address: FrameAddress) -> int | None:
        if address.timeline in {"synchronized", "pose2d", "pose3d"}:
            return address.frame
        return None

    def _raw_person_index(
        self,
        person: PersonAddress,
        camera: str,
        synchronized_frame: int,
    ) -> tuple[int | None, str | None]:
        path = self.project.root / "pose-associated" / "results.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"人物定位层不可读：{exc}"
        if not isinstance(value, dict) or not isinstance(value.get("frames"), list):
            return None, "人物定位层格式无效"
        candidates: set[int] = set()
        for frame in value["frames"]:
            if not isinstance(frame, dict):
                continue
            if frame.get("camera") != camera or frame.get("frame") != synchronized_frame:
                continue
            people = frame.get("people")
            if not isinstance(people, list):
                continue
            for ordinal, record in enumerate(people):
                if not isinstance(record, dict):
                    continue
                if record.get("project_person_id") != person.project_person_id:
                    continue
                raw_index = record.get("raw_person_index", ordinal)
                if isinstance(raw_index, int) and not isinstance(raw_index, bool) and raw_index >= 0:
                    candidates.add(raw_index)
        if not candidates:
            return None, f"人物 {person.project_person_id} 在该相机与同步帧没有唯一定位"
        if len(candidates) > 1:
            return None, f"人物 {person.project_person_id} 在该相机与同步帧存在多个候选"
        resolved = next(iter(candidates))
        if person.raw_person_index is not None and person.raw_person_index != resolved:
            return (
                None,
                f"人物 {person.project_person_id} 的报告索引与当前关联结果不一致",
            )
        return resolved, None

    def _pose_source(
        self,
        target: CorrectionTarget,
        raw_frame: int,
    ) -> tuple[Path | None, tuple[str, ...] | None, str | None]:
        camera = target.address.camera
        path = self.project.root / "pose" / f"{camera}.json"
        if path.is_file():
            return path, None, None
        directory = self.project.root / "pose" / f"{camera}_json"
        frame_path = directory / f"{camera}_{raw_frame:06d}.json"
        if not frame_path.is_file() and directory.is_dir():
            frame_path = next(
                (
                    candidate
                    for candidate in directory.glob(f"{camera}_*.json")
                    if candidate.stem.rsplit("_", 1)[-1].isdigit()
                    and int(candidate.stem.rsplit("_", 1)[-1]) == raw_frame
                ),
                frame_path,
            )
        if not frame_path.is_file():
            return None, None, f"缺少相机 {camera} 原始帧 {raw_frame} 的二维 pose 文件"
        try:
            payload = json.loads(frame_path.read_text(encoding="utf-8"))
            people = payload.get("people") if isinstance(payload, dict) else None
            first_person = people[0] if isinstance(people, list) and people else None
            values = first_person.get("pose_keypoints_2d") if isinstance(first_person, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return frame_path, None, f"二维 pose 文件不可读：{exc}"
        if not isinstance(values, list) or len(values) % 3:
            return frame_path, None, "二维 pose 的关节点数组格式无效"
        keypoint_count = len(values) // 3
        source_index = target.keypoint.source_index
        if source_index is None:
            return frame_path, None, f"关节点 {target.keypoint.keypoint_name} 缺少源索引"
        if source_index >= keypoint_count:
            return frame_path, None, f"关节点 {target.keypoint.keypoint_name} 的源索引超出数组范围"
        names = [f"index-{index:03d}" for index in range(keypoint_count)]
        names[source_index] = target.keypoint.keypoint_name
        return frame_path, tuple(names), None

    def _document(self, path: Path, keypoint_names: tuple[str, ...] | None):
        if keypoint_names is None:
            return PoseDocument(path, project_root=self.project.root)
        camera = path.parent.name.removesuffix("_json")
        frame_text = path.stem.rsplit("_", 1)[-1]
        if not frame_text.isdigit():
            raise ValueError(f"无法从二维 pose 文件名读取帧号：{path.name}")
        repository = Pose2DRepository(
            self.project.root / "pose",
            keypoint_names,
            project_root=self.project.root,
        )
        return repository.load_frame(camera, int(frame_text))

    @staticmethod
    def _blocked(
        issue_id: str,
        blocker: str,
        report_target: CorrectionTarget | None = None,
        synchronized_frame: int | None = None,
        raw_frame: int | None = None,
        mapping_source: str | None = None,
        pose_path: Path | None = None,
        keypoint_names: tuple[str, ...] | None = None,
    ) -> CorrectionResolution:
        return CorrectionResolution(
            issue_id,
            report_target,
            None,
            synchronized_frame,
            raw_frame,
            mapping_source,
            pose_path,
            keypoint_names,
            blocker,
        )
